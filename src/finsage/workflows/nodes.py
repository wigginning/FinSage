"""LangGraph 共享节点（§16 —— m06 T602）。

节点均为工厂函数：``make_<node>(deps)`` 返回可被 LangGraph 调用的 ``Callable[[dict], dict]``，
依赖注入便于测试（retrieval / financial / llm 等外部调用替换为 fake）。

设计约束：
- Node 只修改自己声明的字段（§15）；
- 最终答案仅由 answer_node/abstention_node 产出（其它节点禁止覆写 final_answer）；
- 硬错误（provider timeouts/conflict、计算失败等）捕获后写入 ``error_code``，
  由路由/abstention 决策，不外抛打断整图。
"""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from finsage.exceptions import (
    CalculationError,
    NoEvidenceError,
    ProviderDataConflictError,
    ProviderError,
    ProviderTimeoutError,
    RetrievalError,
)
from finsage.financial.engine import build_calculation, calculate_net_margin
from finsage.governance.audit import InMemoryAuditSink, _Timer, build_entry
from finsage.governance.models import PolicyVerdict, VerificationResult
from finsage.governance.policy import PolicyGate
from finsage.governance.verification import verify
from finsage.models.claims import Claim
from finsage.models.debate import DebateArgument, DebateArgumentsResponse, DebateResult
from finsage.models.entities import Entity, IntentType
from finsage.models.planning import RetrievalPlan
from finsage.observability.trace import uuid_str
from finsage.providers.finance.domain import FinancialMetric


# 节点工厂类型：LangGraph 节点可 sync/async，故拆成"同步节点 | 异步节点"两支联合。
#
# 为什么用 Protocol 而不是 Callable[[dict], ...]：langgraph 的 ``add_node`` 只接受
# ``StateNode``——一组 ``__call__(self, state: NodeInputT) -> Any`` 的 Protocol 联合。
# 任何 ``Callable[[X], Y]`` 都是**仅位置参数**，无法满足"参数可按关键字 ``state=`` 传入"，
# 因此 Callable 形态一律不兼容（与返回类型无关），会让 4 张图的每个 add_node 报
# call-overload。改为具名 ``state`` 参数的 Protocol 即结构匹配。
#
# 代价与约束：**节点函数的首个参数必须命名为 ``state``**（叫 ``s`` 会被类型检查拒绝）。
#
# ``state`` 标 Any 而非具体 State TypedDict：``NodeInputT`` 的上界是
# ``TypedDictLike | DataclassLike | BaseModel``，标 dict 会解到 dict[Any, Any] 违反上界；
# 而 FinSage 的节点工厂按设计被 4 张图共用、只依赖宽松 mapping 语义，不绑定单一 State。
#
# 拆两支而非单个"返回 dict | Awaitable[dict]"：后者表达的是"返回值二者之一"，
# 会让包装器（workflows/reliability.py）无法把返回值收敛回 dict。
class SyncNodeFn(Protocol):
    """同步节点：``(state) -> dict``。"""

    def __call__(self, state: Any) -> dict: ...


class AsyncNodeFn(Protocol):
    """异步节点：``(state) -> Awaitable[dict]``。"""

    def __call__(self, state: Any) -> Awaitable[dict]: ...


NodeFn = SyncNodeFn | AsyncNodeFn


@dataclass
class WorkflowDeps:
    """节点外部依赖（可注入 fake）。"""

    policy: PolicyGate = field(default_factory=PolicyGate)
    audit: Any = field(default_factory=InMemoryAuditSink)
    retrieve: Callable[..., Awaitable[list[Any]]] | None = None  # (query, plan, tenant_id?)
    financial: Callable[..., Awaitable[list[Any]]] | None = None  # async (q, entities)
    calc_runner: Callable[..., list[Any]] | None = None  # (financial_data) -> [Calculation]
    llm: Any | None = None  # LLMProvider stub（可插拔）
    llm_adversarial: Any | None = None  # 对抗视角 LLM（ADR-0009，跨模型家族隔离）


# ---------------------------------------------------------------------------
# 查询解析类（纯规则，禁止外部 Provider）
# ---------------------------------------------------------------------------

def _norm(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip())


# === parse_query_node（§16.2）===
def make_parse_query(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        return {"normalized_query": _norm(str(state.get("query", "")))}

    return _node


# === intent_node（§16.3）===
_INTENT_KEYWORDS: list[tuple[IntentType, tuple[str, ...]]] = [
    ("REALTIME", ("实时", "当前价", "现价", "今天", "最新")),
    ("COMPARISON", ("对比", "比较", "vs", "相比", "差距")),
    ("EXPLANATION", ("为什么", "原因", "为何", "解释")),
    ("DOCUMENT_LOOKUP", ("文档", "报告里", "查找", "lookup")),
    ("RESEARCH", ("研究", "调研", "尽调", "分析报告")),
    ("MULTI_HOP", ("然后", "进而", "以及", "多个")),
    ("NUMERIC", ("多少", "营收", "净利润", "财务", "数据", "指标", "万", "亿", "增长", "率")),
]


def classify_intent(query: str) -> IntentType:
    """按关键词规则分类意图（§16.3 / §21.1）。"""
    low = query.lower()
    for intent, keys in _INTENT_KEYWORDS:
        if any(k.lower() in low for k in keys):
            return intent
    return "FACT"


def make_intent(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        q = state.get("normalized_query") or str(state.get("query", ""))
        return {"intent": classify_intent(q)}

    return _node


# === entity_node（§16.4）===
_TICKER_WITH_MARKET = re.compile(r"([A-Z][A-Z0-9]{0,5})(?:\.(HK|SZ|SH|US))", re.IGNORECASE)
# A 股 6 位数字代码（如 300750 / 600519），前后非数字避免误配年份等。
_CN_TICKER = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_COMPANY_SUFFIX = re.compile(r"[一-龥]{2,}(公司|集团|控股)")


def extract_entities(query: str) -> list[Entity]:
    """确定性抽取实体：优先带市场后缀 ticker，其次 A 股 6 位代码，最后中文公司名。"""
    entities: list[Entity] = []
    seen: set[str] = set()
    for m in _TICKER_WITH_MARKET.finditer(query):
        code, market = m.group(1).upper(), m.group(2).upper()
        key = f"ticker:{code}"
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            Entity(
                type="ticker",
                value=code,
                normalized_value=code,
                market={"HK": "HK", "SZ": "CN.SZ", "SH": "CN.SH", "US": "US"}.get(market),
            )
        )
    if not entities:
        for m in _CN_TICKER.finditer(query):
            code = m.group(1)
            key = f"ticker:{code}"
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                Entity(type="ticker", value=code, normalized_value=code, market="CN")
            )
    if not entities:
        # 不复用上面循环的 m：finditer 产出 Match，search 产出 Match | None，
        # 同名复用会让"可能为 None"这一信息在类型层丢失。
        suffix = _COMPANY_SUFFIX.search(query)
        if suffix and f"company:{suffix.group(0)}" not in seen:
            name = suffix.group(0)
            seen.add(f"company:{name}")
            entities.append(Entity(type="company", value=name, normalized_value=name))
    return entities


def make_entity(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        q = state.get("normalized_query") or str(state.get("query", ""))
        # 合并请求预置实体（RealWorkflowRunner 注入的 company/ticker）与查询抽取实体。
        existing = _to_entities(state.get("entities"))
        extracted = extract_entities(q)
        merged = list(existing)
        for e in extracted:
            if not any(e.type == x.type and e.value == x.value for x in merged):
                merged.append(e)
        return {"entities": merged}

    return _node


# === policy_node（§16.5）===
def _to_entities(raw: list[Any] | None) -> list[Entity]:
    return [
        e for e in (raw or [])
        if isinstance(e, Entity) or (getattr(e, "type", None) and getattr(e, "value", None))
    ]


def make_policy(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        q = state.get("normalized_query") or str(state.get("query", ""))
        entities = _to_entities(state.get("entities"))
        verdict: PolicyVerdict = deps.policy.assess(
            query=q, entities=entities, tools=["rag", "financial_mcp", "calculator"]
        )
        update: dict = {
            "policy_status": verdict.status,
            "warnings": list(state.get("warnings", [])) + list(verdict.warnings),
        }
        if verdict.status == "block":
            update["error_code"] = "FIN-4001"
        return update

    return _node


# === route_node（§16.6）===
def choose_route(state: dict) -> str:
    """按政策/意图/实体确定性选路由（§16.6）。"""
    if state.get("policy_status") == "block" or state.get("error_code"):
        return "ABSTAIN"
    intent = state.get("intent") or "UNKNOWN"
    has_ticker = any(
        getattr(e, "type", None) == "ticker"
        for e in _to_entities(state.get("entities"))
    )
    if intent in ("NUMERIC", "REALTIME"):
        return "FINANCIAL_MCP" if has_ticker else "COMBINED"
    if intent in ("RESEARCH", "MULTI_HOP"):
        return "COMBINED"
    return "RAG"


def make_route(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        return {"retrieval_plan": RetrievalPlan()}

    return _node


# ---------------------------------------------------------------------------
# 检索 / 财务数据 / 计算（外部 IO）
# ---------------------------------------------------------------------------

# === retrieval_node（§16.7）===
def make_retrieval(deps: WorkflowDeps) -> NodeFn:
    async def _node(state: dict) -> dict:
        q = state.get("normalized_query") or str(state.get("query", ""))
        plan: RetrievalPlan | None = state.get("retrieval_plan") or RetrievalPlan()
        if deps.retrieve is None:
            return {"evidences": []}
        try:
            # P0 检索跨租户隔离：透传 tenant_id 给检索适配器（Milvus expr 强制租户过滤）。
            evidences = await deps.retrieve(q, plan, tenant_id=state.get("tenant_id"))
            return {"evidences": list(evidences or [])}
        except NoEvidenceError:
            return {"evidences": [], "error_code": "FIN-3003"}
        except RetrievalError as exc:
            return {"evidences": [], "error_code": exc.code.value}

    return _node


# === financial_data_node（§16.8）===
def make_financial_data(deps: WorkflowDeps) -> NodeFn:
    async def _node(state: dict) -> dict:
        q = state.get("normalized_query") or str(state.get("query", ""))
        entities = _to_entities(state.get("entities"))
        if deps.financial is None:
            return {"financial_data": []}
        try:
            data = await deps.financial(q, entities)
            # P2 冲突检测接线：跨 Provider 数值冲突不得静默忽略（AGENTS.md §3），
            # 命中冲突写入 data_conflict（供 V007 阻断高置信 + 置信度封顶）。
            from finsage.providers.finance.conflict import detect_metric_conflicts

            conflicts = detect_metric_conflicts(list(data or []))
            update: dict = {"financial_data": list(data or [])}
            if conflicts:
                update["data_conflict"] = True
                update["warnings"] = list(state.get("warnings") or []) + [
                    "provider_data_conflict"
                ]
            return update
        except ProviderTimeoutError:
            return {"error_code": "FIN-2001"}
        except ProviderDataConflictError:
            return {"financial_data": [], "error_code": "FIN-2101"}
        except (ProviderError, RetrievalError) as exc:
            # 覆盖 ProviderBadResponseError / MarketDataUnavailableError 等，
            # 诚实映射 error_code 而不让 Provider 异常击穿整图。
            return {"error_code": exc.code.value}

    return _node


# === calculation_node（§16.9，确定性引擎）===
def _default_calc_runner(
    financial_data: list[Any], evidences: list[Any] | None = None
) -> list[Any]:
    """确定性派生指标：同一期间内用 revenue/net_income 计算净利率（§22）。

    P2 溯源：把与指标同 (company,ticker,market) 且文本含指标名的证据 id 关联到
    Calculation.source_evidence_ids，修复"恒为空"（审计 §2.9）。
    """
    by_key: dict[tuple[str, str], dict] = {}
    for m in financial_data:
        if not isinstance(m, FinancialMetric):
            continue
        bucket = by_key.setdefault((m.period, m.currency or ""), {})
        bucket[m.metric] = m
    evidence_map = _evidence_ids_for_metrics(evidences, financial_data)
    calcs: list[Any] = []
    for (period, _), row in by_key.items():
        rev = row.get("revenue")
        ni = row.get("net_income")
        if ni is None or rev is None or rev.value == 0:
            continue
        ratio = calculate_net_margin(ni.value, rev.value)
        key = (ni.company, ni.ticker, ni.market, period)
        calcs.append(
            build_calculation(
                formula="net_income / revenue",
                inputs={"net_income": ni.value, "revenue": rev.value},
                output_value=ratio,
                output_unit="ratio",
                period=period,
                source_evidence_ids=list(evidence_map.get(key, [])),
            )
        )
    return calcs


def _evidence_ids_for_metrics(
    evidences: list[Any] | None, financial_data: list[Any]
) -> dict[tuple[str, str, str, str], list[str]]:
    """按 (company, ticker, market, period) 建立证据 id 索引（溯源关联）。

    证据文本含公司 ticker 或公司名，或含 period 年份的，视为该指标的支撑证据。
    """
    from finsage.providers.finance.domain import FinancialMetric

    index: dict[tuple[str, str, str, str], list[str]] = {}
    if not evidences:
        return index
    for m in financial_data:
        if not isinstance(m, FinancialMetric):
            continue
        key = (m.company, m.ticker, m.market, m.period)
        index.setdefault(key, [])
    for ev in evidences or []:
        eid = getattr(ev, "id", "")
        text = (getattr(ev, "text", "") or "").lower()
        if not eid:
            continue
        for m in financial_data:
            if not isinstance(m, FinancialMetric):
                continue
            key = (m.company, m.ticker, m.market, m.period)
            hit = (m.ticker and m.ticker.lower() in text) or (
                m.company and m.company.lower() in text
            )
            if hit and m.period in text:
                index.setdefault(key, [])
                if eid not in index[key]:
                    index[key].append(eid)
    return index


# === 估值接线（ADR-0018）===
# 估值类查询按查询文本确定性判定（不改动 §4.1 冻结的 IntentType 枚举）。
_VALUATION_KEYWORDS: tuple[str, ...] = (
    "估值", "dcf", "折现", "内在价值", "企业价值", "合理价格", "valuation",
)


def is_valuation_query(query: str) -> bool:
    """判定是否为估值类查询（确定性关键词，不调用 LLM）。"""
    low = (query or "").lower()
    return any(k in low for k in _VALUATION_KEYWORDS)


def _valuation_calculations(
    financial_data: list[Any], evidences: list[Any]
) -> tuple[list[Any], list[str]]:
    """估值类确定性派生（ADR-0018），返回 (calculations, warnings)。

    诚实边界（AGENTS.md §10）：
    - 增长率外推用**历史真实增速**（calculate_growth 推导），不是假设；
      历史不足两期时跳过，不臆造增长率。
    - DCF 的 WACC / 永续增长率是分析师假设，仅当显式配置
      ``valuation_wacc`` / ``valuation_terminal_growth`` 才计算；
      未配置时跳过并记 warning，绝不套用"行业惯例默认值"。
    """
    from finsage.financial.engine import calculate_growth
    from finsage.financial.valuation import calculate_dcf, project_growth
    from finsage.settings import get_settings

    warnings: list[str] = []
    calcs: list[Any] = []

    # 按 metric 取按期间升序的历史序列。
    by_metric: dict[str, list[Any]] = {}
    for m in financial_data:
        if not isinstance(m, FinancialMetric):
            continue
        by_metric.setdefault(m.metric, []).append(m)
    for series in by_metric.values():
        series.sort(key=lambda m: m.period or "")

    # 1) 增长率外推：以最近两期的真实同比增速外推（确定性，非假设）。
    settings = get_settings()
    periods = max(1, int(settings.valuation_projection_periods or 3))
    for metric, series in by_metric.items():
        if len(series) < 2:
            continue
        prev, last = series[-2], series[-1]
        if not prev.value:
            continue
        try:
            growth = calculate_growth(last.value, prev.value)
            projected = project_growth(last.value, growth, periods)
        except CalculationError:
            continue
        calcs.append(
            build_calculation(
                formula=f"project_growth({metric}, g={growth}, n={periods})",
                inputs={metric: last.value, "growth_rate": growth},
                output_value=projected[-1],
                output_unit=getattr(last, "unit", None),
                period=str(last.period) if last.period else None,
                source_evidence_ids=list(
                    _evidence_ids_for_metrics(evidences, [last]).get(
                        (last.company, last.ticker, last.market, last.period), []
                    )
                ),
            )
        )

    # 2) DCF：仅当假设显式配置时才计算。
    wacc, term_g = settings.valuation_wacc, settings.valuation_terminal_growth
    fcf_series = by_metric.get("free_cash_flow") or by_metric.get("operating_cash_flow")
    if fcf_series and wacc is not None and term_g is not None:
        try:
            dcf = calculate_dcf([m.value for m in fcf_series], wacc, term_g)
        except CalculationError as exc:
            warnings.append(f"dcf_invalid_assumption:{exc.code.value}")
        else:
            last = fcf_series[-1]
            calcs.append(
                build_calculation(
                    formula=f"dcf(fcf[{len(fcf_series)}], wacc={wacc}, g={term_g})",
                    inputs={"wacc": wacc, "terminal_growth": term_g},
                    output_value=dcf.enterprise_value,
                    output_unit=getattr(last, "unit", None),
                    period=str(last.period) if last.period else None,
                    source_evidence_ids=list(
                        _evidence_ids_for_metrics(evidences, fcf_series).get(
                            (last.company, last.ticker, last.market, last.period), []
                        )
                    ),
                )
            )
    elif fcf_series:
        warnings.append("dcf_skipped:valuation_assumptions_not_configured")

    return calcs, warnings


def make_calculation(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        financial = state.get("financial_data") or []
        evidences = state.get("evidences") or []
        runner = deps.calc_runner or _default_calc_runner
        try:
            # P2 溯源：把证据传入计算器以关联 source_evidence_ids。
            # 兼容只接受 financial_data 的自定义 calc_runner（既有调用形态）。
            if deps.calc_runner is not None and not _accepts_two_args(deps.calc_runner):
                calculations = list(runner(financial) or [])
            else:
                calculations = list(runner(financial, evidences) or [])
        except CalculationError:
            return {"calculations": [], "error_code": "FIN-3101"}

        # ADR-0018：估值类查询追加估值派生计算（与既有净利率同源同规则）。
        warnings: list[str] = []
        if is_valuation_query(str(state.get("query", ""))):
            valuation_calcs, valuation_warnings = _valuation_calculations(
                financial, evidences
            )
            calculations = calculations + valuation_calcs
            warnings = valuation_warnings

        update: dict = {"calculations": calculations}
        if warnings:
            update["warnings"] = list(state.get("warnings") or []) + warnings
        return update

    return _node


def _accepts_two_args(fn: Any) -> bool:
    """判断 calc_runner 是否接受 (financial_data, evidences) 两个位置参数。"""
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # noqa: BLE001 - 内置/不可内省调用对象
        return True  # 保守：按默认双参调用
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(p.kind == p.VAR_POSITIONAL for p in sig.parameters.values())
    if has_varargs:
        return True
    return len(positional) >= 2


# ---------------------------------------------------------------------------
# 证据筛选 / 论断生成 / 校验 / 放弃 / 作答 / 审计
# ---------------------------------------------------------------------------

# === evidence_selection_node（§16.10，最多 10 条）===
MAX_EVIDENCE = 10


def make_evidence_selection(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        unique: dict[str, Any] = {}
        for e in list(state.get("evidences") or []):
            # 无 id 的证据对象按对象身份去重（键统一为 str，避免混型键）。
            ev_id = getattr(e, "id", None)
            unique[str(ev_id) if ev_id is not None else f"anon:{id(e)}"] = e
        ranked = sorted(
            unique.values(),
            key=lambda e: getattr(e, "relevance_score", 0.0) or 0.0,
            reverse=True,
        )
        return {"evidences": ranked[:MAX_EVIDENCE]}

    return _node


# === claim_generation_node（§16.11）===
# 确定性计算型论断的置信度基准：计算本身是确定性的，但无证据绑定时不冒充高置信。
_CALC_CLAIM_UNBOUND_CONFIDENCE = 0.5


def _calc_claim_confidence(calc: Any, evidences: list[Any]) -> float:
    """计算型论断的确定性置信度（替换硬编码 0.9）。

    口径：确定性引擎产出的数值本身可信，但置信度仍需反映"是否可溯源到证据"。
    - 计算的 source_evidence_ids 能解析到实际证据 → 取这些证据 (relevance+authority)/2 均值；
    - 无绑定证据 → 固定 0.5（确定性但不可溯源，不冒充高置信，AGENTS.md §10）。
    """
    bound_ids = list(getattr(calc, "source_evidence_ids", []) or [])
    if not bound_ids or not evidences:
        return _CALC_CLAIM_UNBOUND_CONFIDENCE
    by_id = {getattr(e, "id", ""): e for e in evidences}
    matched = [by_id[eid] for eid in bound_ids if eid in by_id]
    if not matched:
        return _CALC_CLAIM_UNBOUND_CONFIDENCE
    relevance = [float(getattr(e, "relevance_score", 0.0) or 0.0) for e in matched]
    authority = [float(getattr(e, "authority_score", 0.0) or 0.0) for e in matched]
    return round(
        max(
            _CALC_CLAIM_UNBOUND_CONFIDENCE,
            (sum(relevance) / len(relevance) + sum(authority) / len(authority)) / 2,
        ),
        4,
    )


def _make_claims(evidences: list[Any], calculations: list[Any]) -> list[Claim]:
    """由证据/计算确定性生成论断（满足 V001/V002/V003）。"""
    claims: list[Claim] = []
    for i, e in enumerate(evidences):
        text = (getattr(e, "text", "") or "").strip()
        claims.append(
            Claim(
                id=uuid_str(),
                text=f"依据证据发现：{text[:120]}",
                claim_type="fact",
                evidence_ids=[getattr(e, "id", f"ev:{i}")],
                confidence=round(float(getattr(e, "relevance_score", 0.0) or 0.0), 4),
            )
        )
    for i, c in enumerate(calculations):
        formula = getattr(c, "formula", "")
        out_val = getattr(c, "output_value", None)
        claims.append(
            Claim(
                id=uuid_str(),
                text=f"由确定性计算得到 {formula} = {out_val}",
                claim_type="numeric",
                calculation_id=getattr(c, "id", f"calc:{i}"),
                evidence_ids=list(getattr(c, "source_evidence_ids", []) or []),
                confidence=_calc_claim_confidence(c, evidences),
            )
        )
    return claims


def make_claim_generation(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        from finsage.governance.policy import sanitize_retrieved_content

        evidences = list(state.get("evidences") or [])
        # P1 检索内容 Prompt Injection 防御：外部文档是不可信输入，注入片段不进 LLM。
        ev_texts = [getattr(e, "text", "") or "" for e in evidences]
        safe_texts, inject_warnings = sanitize_retrieved_content(ev_texts)
        # 用净化后的证据文本生成论断（保持数量对齐，注入片段降为占位）。
        safe_evidences = list(evidences)
        for i, safe in enumerate(safe_texts):
            if safe != ev_texts[i]:
                safe_evidences[i] = _with_text(evidences[i], safe)

        claims = _make_claims(
            list(safe_evidences or []),
            list(state.get("calculations") or []),
        )
        draft = "\n".join(f"- {c.text}" for c in claims)
        update: dict = {"claims": claims, "draft_answer": draft}
        if deps.llm is not None:
            # P0 会话记忆：注入历史上下文（续聊），仅作背景提示，不改变论断事实来源。
            history = state.get("chat_history") or []
            prompt = draft
            if history:
                history_lines = "\n".join(
                    f"{h.get('role', '')}: {h.get('content', '')}"
                    for h in history[-6:]  # 最近 6 轮，控制上下文窗口
                )
                prompt = f"历史对话：\n{history_lines}\n\n本轮待综合内容：\n{draft}"
            try:
                update["draft_answer"] = deps.llm.complete(
                    system="合成研究结论", prompt=prompt
                )
            except Exception as exc:  # noqa: BLE001 - LLM 失败不回退（保留确定性草稿）
                from finsage.observability.logger import get_logger

                get_logger(__name__).warning(
                    "claim_generation.llm_failed",
                    extra={"extra": {"error": type(exc).__name__}},
                )
                # 保持确定性草稿 + 告警，不让 LLM 失败击穿整图（P1）。
                update["warnings"] = list(state.get("warnings") or []) + [
                    "claim_llm_failed_fallback_deterministic"
                ]
        if inject_warnings:
            update["warnings"] = list(state.get("warnings") or []) + inject_warnings
        return update

    return _node


def _with_text(ev: Any, text: str) -> Any:
    """对 Evidence 对象做只读替换 text 的安全处理（避免改原对象状态）。"""
    try:
        import dataclasses

        # 排除"传入的是 dataclass 类本身"——is_dataclass 对类也返回 True，
        # 而 replace() 只能作用于实例，对类调用会在运行时抛错。
        if dataclasses.is_dataclass(ev) and not isinstance(ev, type):
            return dataclasses.replace(ev, text=text)
    except Exception:  # noqa: BLE001 - 非 dataclass/pydantic 走复制兜底
        pass
    # pydantic 模型：model_copy(update=...)。
    copier = getattr(ev, "model_copy", None)
    if callable(copier):
        return copier(update={"text": text})
    # 兜底：绕过构造函数做浅拷贝（动态类型，故显式标 Any）。
    cls: Any = type(ev)
    new = cls.__new__(cls)
    new.__dict__.update(ev.__dict__)
    new.text = text
    return new


# === sentiment_node（ADR-0011 / ADR-0018，证据情绪富化）===
def make_sentiment(deps: WorkflowDeps) -> NodeFn:
    """对已筛选证据做规则法情绪聚合（确定性，不调用 LLM）。

    AGENTS.md §6：只写自己声明的字段（``sentiment_summary``）。
    结果 ``calibrated=False``，任何呈现层都必须标注"未校准"。
    """

    def _node(state: dict) -> dict:
        from finsage.sentiment import summarize_sentiment

        texts = [getattr(e, "text", "") or "" for e in list(state.get("evidences") or [])]
        summary = summarize_sentiment([t for t in texts if t.strip()])
        return {"sentiment_summary": summary if summary.analyzed else None}

    return _node


# === debate_node（ADR-0009，§F4 多空辩论）===
def _derive_arguments(side: str, claims: list[Any]) -> list[DebateArgument]:
    """确定性推导论点：bull 回显论断并挂证据；bear 质疑低置信/无证据论断。

    bear 对"无证据绑定或低置信"的论断降级（confidence = 1 - claim.confidence，
    无 evidence_ids），而非硬拒绝——硬拒绝仍由 verification（V001/V002/V003）负责。
    """
    args: list[DebateArgument] = []
    for c in claims:
        text = (getattr(c, "text", "") or "").strip()
        if not text:
            continue
        evidence_ids = list(getattr(c, "evidence_ids", []) or [])
        confidence = float(getattr(c, "confidence", 0.0) or 0.0)
        if side == "bull":
            args.append(
                DebateArgument(
                    side="bull",
                    text=f"支持：{text}",
                    evidence_ids=evidence_ids,
                    confidence=round(confidence, 4),
                )
            )
        else:
            if not evidence_ids or confidence < 0.5:
                args.append(
                    DebateArgument(
                        side="bear",
                        text=f"质疑：{text}（证据不足或置信度低，待核实）",
                        evidence_ids=[],
                        confidence=round(1.0 - confidence, 4),
                    )
                )
    return args


def _llm_arguments(
    side: str, claims: list[Any], evidence_ids: set[str], llm: Any
) -> list[DebateArgument] | None:
    """可选 LLM 增强：结构化生成论点（schema 绑定），失败返回 None 回退确定性推导。

    契约：LLM 返回 ``DebateArgumentsResponse``（Pydantic schema，ADR-0012）。
    ``evidence_ids`` 必须能解析到真实证据，否则该论点降级（清空引用、置信度减半）。
    LLM 只生成论点文本，不裁决算术（AGENTS.md §3）。
    """
    if llm is None:
        return None
    try:
        resp = llm.complete_typed(
            system=(
                "你是金融研究的多空辩论方。仅生成论点文本，不得进行任何算术计算。"
                "输出 JSON 对象，含 arguments 数组，每项：text / evidence_ids / confidence。"
            ),
            prompt=(
                f"立场：{side}。基于以下论断生成论点："
                f"{json.dumps([getattr(c, 'text', '') for c in claims], ensure_ascii=False)}"
            ),
            schema=DebateArgumentsResponse,
        )
        args: list[DebateArgument] = []
        for draft in resp.arguments:
            text = draft.text.strip()
            if not text:
                continue
            eids = list(draft.evidence_ids)
            conf = max(0.0, min(1.0, draft.confidence))
            # 数值声明未挂真实来源 -> 降级（清空引用、置信度减半），而非硬拒绝。
            if any(eid not in evidence_ids for eid in eids):
                eids = []
                conf = conf / 2.0
            args.append(
                DebateArgument(
                    side=side, text=text, evidence_ids=eids, confidence=round(conf, 4)
                )
            )
        return args or None
    except Exception:
        return None


def arbitrate_debate(
    bull: list[DebateArgument], bear: list[DebateArgument]
) -> DebateResult:
    """确定性仲裁（ADR-0009）：分歧度 = 多空证据集 Jaccard 距离，verdict 由聚合置信度决定。

    - 无空方反对 -> disagreement 0.0 / verdict bull；
    - 无多方 -> disagreement 1.0 / verdict bear；
    - 双方证据集不相交 -> disagreement 1.0；完全重叠 -> 0.0。
    """
    if not bull and not bear:
        return DebateResult(disagreement=0.0, verdict="insufficient")
    if not bear:
        return DebateResult(bull_arguments=bull, disagreement=0.0, verdict="bull")
    if not bull:
        return DebateResult(bear_arguments=bear, disagreement=1.0, verdict="bear")

    bull_evidence = {eid for a in bull for eid in a.evidence_ids}
    bear_evidence = {eid for a in bear for eid in a.evidence_ids}
    union = bull_evidence | bear_evidence
    if not union:
        disagreement = 0.5
    else:
        overlap = bull_evidence & bear_evidence
        disagreement = 1.0 - (len(overlap) / len(union))

    bull_conf = sum(a.confidence for a in bull) / len(bull)
    bear_conf = sum(a.confidence for a in bear) / len(bear)
    if abs(bull_conf - bear_conf) < 0.1:
        verdict = "balanced"
    elif bull_conf > bear_conf:
        verdict = "bull"
    else:
        verdict = "bear"

    return DebateResult(
        bull_arguments=bull,
        bear_arguments=bear,
        disagreement=round(disagreement, 4),
        verdict=verdict,
    )


def make_debate(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        claims = list(state.get("claims") or [])
        evidence_ids = {
            getattr(e, "id", f"ev:{i}") for i, e in enumerate(state.get("evidences") or [])
        }
        bull = _derive_arguments("bull", claims)
        bear = _derive_arguments("bear", claims)
        # 可选 LLM 增强（跨模型家族隔离：bear 用 llm_adversarial）；失败回退确定性推导。
        bull = _llm_arguments("bull", claims, evidence_ids, deps.llm) or bull
        bear = (
            _llm_arguments("bear", claims, evidence_ids, deps.llm_adversarial or deps.llm)
            or bear
        )
        return {"debate_result": arbitrate_debate(bull, bear)}

    return _node


# === verification_node（§16.12 / §23）===
def make_verification(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        result: VerificationResult = verify(
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            policy_status=state.get("policy_status"),
            data_conflicts=(
                ["provider_data_conflict"] if state.get("data_conflict") else []
            ),
        )
        if result.status == "PASS":
            return {"verification_result": result}
        update: dict = {"verification_result": result}
        if result.status == "FAIL":
            update["error_code"] = "FIN-4101"
        return update

    return _node


# === abstention_node（§16.13 / §23 V008/V010）===
def make_abstention(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        from finsage.models.claims import ResearchAnswer

        reason = state.get("error_code") or "insufficient_evidence"
        warnings = list(state.get("warnings", [])) + [f"abstained:{reason}"]
        ans = ResearchAnswer(
            answer=f"本次查询无法给出高置信结论（原因：{reason}）。",
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            confidence=0.0,
            warnings=warnings,
        )
        return {"final_answer": ans, "warnings": warnings, "confidence": 0.0}

    return _node


# === answer_node（§16.14）===
def compute_answer_confidence(state: dict) -> float:
    """按 §24 六因素确定性计算整体置信度（替换硬编码 0.9）。

    因素来源（全部确定性，不靠 LLM 自评）：
    - retrieval_quality：证据相关分均值（无证据 → 0）；
    - evidence_authority：证据权威分均值；
    - evidence_coverage：claims 绑定的证据覆盖率（无 claims 无证据 → 0）；
    - calculation_validity：有计算且均通过 → 1，有计算全失败 → 0；
    - temporal_validity：期间与请求一致 → 1（无期间约束按 1）；
    - verification_status：来自 verification_result（PASS/FAIL/ABSTAIN）；
    - data_conflict：是否命中数据冲突（封顶阻断高置信）。
    """
    from finsage.governance.confidence import compute_confidence

    evidences = list(state.get("evidences") or [])
    calculations = list(state.get("calculations") or [])
    claims = list(state.get("claims") or [])

    if not evidences and not calculations:
        # 完全无支撑：检索 0 + 计算 0 -> 置信度归零，绝不硬编码高值（审计 L2）。
        return 0.0

    relevance = [
        float(getattr(e, "relevance_score", 0.0) or 0.0) for e in evidences
    ]
    authority = [
        float(getattr(e, "authority_score", 0.0) or 0.0) for e in evidences
    ]
    retrieval_quality = sum(relevance) / len(relevance) if relevance else 0.0
    evidence_authority = sum(authority) / len(authority) if authority else 0.0

    # 覆盖率：claims 实际绑定证据的比例；无 claims 时按有无证据判断。
    bound = sum(1 for c in claims if getattr(c, "evidence_ids", None))
    coverage = (bound / len(claims)) if claims else (1.0 if evidences else 0.0)

    # 计算有效性：有计算且产出非空视为有效（确定性引擎成功）。
    calc_validity = 1.0 if calculations else 0.0

    # 期间一致性：expected_period 若给定，全部计算期间须匹配。
    expected_period = state.get("expected_period")
    temporal = 1.0
    if expected_period:
        mismatched = any(
            getattr(c, "period", None) and c.period != expected_period
            for c in calculations
        )
        temporal = 0.0 if mismatched else 1.0

    vr = state.get("verification_result")
    verify_status = getattr(vr, "status", None) or "ABSTAIN"

    score = compute_confidence(
        retrieval_quality=retrieval_quality,
        evidence_authority=evidence_authority,
        evidence_coverage=coverage,
        calculation_validity=calc_validity,
        temporal_validity=temporal,
        verification_status=verify_status,
        data_conflict=bool(state.get("data_conflict")),
    )
    return score.score


def make_answer(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        from finsage.models.claims import ResearchAnswer

        debate = state.get("debate_result")
        confidence = compute_answer_confidence(state)
        ans = ResearchAnswer(
            answer=state.get("draft_answer") or "基于证据与计算完成回答。",
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            confidence=confidence,
            warnings=state.get("warnings") or [],
            # ADR-0018：辩论分歧度与情绪聚合同链路下发（此前两处组装时都被丢弃）。
            disagreement=getattr(debate, "disagreement", None),
            sentiment_summary=state.get("sentiment_summary"),
        )
        return {"final_answer": ans, "confidence": confidence}

    return _node


# === audit_node（§16.15 / §25）===
def make_audit(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        from finsage.observability.logger import get_logger

        timer = _Timer()
        entry = build_entry(
            state=state,
            stage="end",
            actor="research_qa",
            status="error" if state.get("error_code") else "success",
            output_summary=(
                {"answer": str(getattr(state.get("final_answer"), "answer", ""))[:80]}
                if state.get("final_answer")
                else None
            ),
            error_code=state.get("error_code"),
            latency_ms=timer.ms(),
        )
        audit_id = uuid_str()
        try:
            deps.audit.record(entry)
        except Exception as exc:  # noqa: BLE001 - 审计 sink 故障不得拖垮主流程
            # 埋点：审计写入失败可见（异常信息脱敏，仅记类型，不落 secret）。
            get_logger(__name__).warning(
                "audit_sink_failed",
                extra={
                    "io_point": "audit.record",
                    "exc_type": type(exc).__name__,
                    "trace_id": state.get("trace_id"),
                },
            )
        return {"audit_id": audit_id}

    return _node


__all__ = [
    "WorkflowDeps",
    "make_parse_query",
    "make_intent",
    "make_entity",
    "make_policy",
    "make_route",
    "make_retrieval",
    "make_financial_data",
    "make_calculation",
    "make_evidence_selection",
    "make_claim_generation",
    "make_sentiment",
    "make_debate",
    "arbitrate_debate",
    "make_verification",
    "make_abstention",
    "make_answer",
    "make_audit",
    "classify_intent",
    "extract_entities",
    "choose_route",
    "compute_answer_confidence",
    "is_valuation_query",
    "_default_calc_runner",
    "_valuation_calculations",
]