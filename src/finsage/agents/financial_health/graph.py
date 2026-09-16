"""T604 Financial Health Graph（§18 —— FROZEN 顺序）。

```text
START → parse_query → entity → policy → financial_data
     → financial_rule_engine → financial_calculation → narrative_analysis
     → cross_check → claim_generation → verification
     → (PASS) report → audit → END / (FAIL/ABSTAIN) abstain → audit → END
```

确定性原则（AGENTS.md §3/§6）：
- financial_rule_engine / financial_calculation 由 Python 计算，不调用 LLM；
- narrative_analysis / report 为确定性模板渲染；
- 各节点仅写自己声明的字段；final_answer 仅由 report/abstain 产出；
- 硬错误写入 error_code，由 verification 路由决策，不外抛。

本包使用独立 ``FinancialHealthState``（§15 的 ResearchState 为 Research QA 专用，
Rule/叙事/交叉核对是 Health 图独有字段；两者共用同一套共享节点工厂）。
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from finsage.financial.engine import calculate_net_margin
from finsage.financial.models import Calculation
from finsage.models.claims import ResearchAnswer
from finsage.models.entities import Entity
from finsage.providers.finance.domain import FinancialMetric
from finsage.workflows.nodes import (
    NodeFn,
    WorkflowDeps,
    make_abstention,
    make_audit,
    make_calculation,
    make_claim_generation,
    make_entity,
    make_financial_data,
    make_parse_query,
    make_policy,
    make_verification,
)

HealthStatus = Literal["healthy", "watch", "warning"]


class FinancialHealthState(TypedDict, total=False):
    """§18 Financial Health 图运行状态。"""

    request_id: str
    trace_id: str
    task_id: str
    query: str
    normalized_query: str | None
    intent: str | None
    entities: list[Entity]
    policy_status: str | None
    warnings: list[str]
    financial_data: list[FinancialMetric]
    calculations: list[Calculation]
    rule_results: list[str]
    health_status: HealthStatus | None
    health_score: float | None
    narrative: str | None
    cross_check_status: str | None
    claims: list[Any]
    draft_answer: str | None
    verification_result: Any | None
    confidence: float | None
    final_answer: ResearchAnswer | None
    error_code: str | None


# === financial_rule_engine（§18，确定性财务规则）===
# 净利率阈值：>=20% healthy / >=5% watch / 其余 warning。
_MARGIN_HEALTHY = 0.20
_MARGIN_WATCH = 0.05


def _nested_margin(data: list[FinancialMetric]) -> list[dict[str, Any]]:
    """按 period 归并同一报表期内的指标，返回带净利率的行。"""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for m in data:
        key = (m.period, m.currency or "")
        row = by_key.setdefault(key, {"period": m.period, "currency": m.currency or ""})
        row[m.metric] = m
    rows: list[dict[str, Any]] = []
    for row in by_key.values():
        rev = row.get("revenue")
        ni = row.get("net_income")
        if ni is None or rev is None or rev.value == 0:
            continue
        rows.append({"period": row["period"], "margin": calculate_net_margin(ni.value, rev.value)})
    return rows


def make_financial_rule_engine(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        rows = _nested_margin(list(state.get("financial_data") or []))
        rules: list[str] = []
        for r in rows:
            margin = r["margin"]
            tag = (
                "healthy"
                if margin >= _MARGIN_HEALTHY
                else ("watch" if margin >= _MARGIN_WATCH else "warning")
            )
            rules.append(f"{r['period']}: net_margin={margin:.2%} -> {tag}")
        score: float | None = None
        status: HealthStatus | None = None
        if rows:
            avg = sum(r["margin"] for r in rows) / len(rows)
            score = round(avg, 4)
            status = (
                "healthy"
                if avg >= _MARGIN_HEALTHY
                else ("watch" if avg >= _MARGIN_WATCH else "warning")
            )
        return {"rule_results": rules, "health_score": score, "health_status": status}

    return _node


# === narrative_analysis（§18，确定性叙事模板）===
def make_narrative_analysis(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        calc = list(state.get("calculations") or [])
        rules = list(state.get("rule_results") or [])
        parts: list[str] = ["财务健康分析："]
        if rules:
            parts.append("；".join(rules))
        elif calc:
            parts.append(f"完成 {len(calc)} 项确定性计算。")
        else:
            parts.append("暂无可支撑的财务计算（等待补充数据）。")
        return {"narrative": "".join(parts)}

    return _node


# === cross_check（§18，确定性交叉核对）===
# 规则：存在财务数据但无法派生出任何净利率计算，且查询预期数值 -> 视为数据不足。
def make_cross_check(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        financial = list(state.get("financial_data") or [])
        calcs = list(state.get("calculations") or [])
        if financial and not calcs and not state.get("rule_results"):
            return {"cross_check_status": "conflict", "error_code": "FIN-2101"}
        return {"cross_check_status": "ok"}

    return _node


# === report（§18，确定性渲染，终态）===
def make_report(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        ans = ResearchAnswer(
            answer=(
                state.get("narrative")
                or state.get("draft_answer")
                or "基于确定性财务计算完成健康度分析。"
            ),
            claims=list(state.get("claims") or []),
            evidences=[],
            calculations=list(state.get("calculations") or []),
            confidence=(
                round(float(state.get("confidence") or 0.0), 4)
                if state.get("confidence") is not None
                else 0.9
            ),
            warnings=list(state.get("warnings") or []),
        )
        return {"final_answer": ans, "confidence": ans.confidence}

    return _node


def _io(
    node: Any, name: str, timeouts: dict[str, float], node_timeout: float
) -> Any:
    """按图级与节点级超时包裹 IO 节点（仅对 async 生效）。"""
    from finsage.workflows.reliability import with_timeout

    secs = timeouts.get(name, node_timeout)
    return with_timeout(node, secs) if secs and secs > 0 else node


def _policy_gate(state: dict) -> str:
    """§16.6 路由语义：政策 block / 已有错误 -> 放弃；否则继续拉取财务数据。"""
    if state.get("policy_status") == "block" or state.get("error_code"):
        return "abstain"
    return "continue"


def build_financial_health(
    deps: WorkflowDeps | None = None,
    *,
    checkpointer: Any = None,
    timeouts: dict[str, float] | None = None,
    node_timeout: float = 0,
) -> Any:
    """装配 §18 Financial Health 图。checkpointer 注入实现 T607 持久化。"""
    from langgraph.graph import END, START, StateGraph

    deps = deps or WorkflowDeps()
    timeouts = dict(timeouts or {})

    graph = StateGraph(FinancialHealthState)
    graph.add_node("parse_query", make_parse_query(deps))
    graph.add_node("entity", make_entity(deps))
    graph.add_node("policy", make_policy(deps))
    graph.add_node(
        "financial_data",
        _io(make_financial_data(deps), "financial_data", timeouts, node_timeout),
    )
    graph.add_node("financial_rule_engine", make_financial_rule_engine(deps))
    graph.add_node("financial_calculation", make_calculation(deps))
    graph.add_node("narrative_analysis", make_narrative_analysis(deps))
    graph.add_node("cross_check", make_cross_check(deps))
    graph.add_node("claim_generation", make_claim_generation(deps))
    graph.add_node("verification", make_verification(deps))
    graph.add_node("report", make_report(deps))
    graph.add_node("abstain", make_abstention(deps))
    graph.add_node("audit", make_audit(deps))

    graph.add_edge(START, "parse_query")
    graph.add_edge("parse_query", "entity")
    graph.add_edge("entity", "policy")

    # 政策拦截（投资建议/注入/越权工具）不拉取财务数据，直接放弃（同 §16.6 路由 ABSTAIN）。
    graph.add_conditional_edges(
        "policy",
        _policy_gate,
        {"continue": "financial_data", "abstain": "abstain"},
    )
    graph.add_edge("financial_data", "financial_rule_engine")
    graph.add_edge("financial_rule_engine", "financial_calculation")
    graph.add_edge("financial_calculation", "narrative_analysis")
    graph.add_edge("narrative_analysis", "cross_check")
    graph.add_edge("cross_check", "claim_generation")
    graph.add_edge("claim_generation", "verification")

    def _after_verify(state: dict) -> str:
        status = getattr(state.get("verification_result"), "status", None)
        if status == "PASS" and state.get("cross_check_status") != "conflict":
            return "report"
        return "abstain"

    graph.add_conditional_edges(
        "verification",
        _after_verify,
        {"report": "report", "abstain": "abstain"},
    )
    graph.add_edge("report", "audit")
    graph.add_edge("abstain", "audit")
    graph.add_edge("audit", END)

    return graph.compile(checkpointer=checkpointer)


__all__ = [
    "FinancialHealthState",
    "build_financial_health",
    "make_financial_rule_engine",
    "make_narrative_analysis",
    "make_cross_check",
    "make_report",
]