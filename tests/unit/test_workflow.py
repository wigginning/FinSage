"""m06 LangGraph 确定性工作流测试（T608/T609，§28.4）。

覆盖：
- 节点：parse/intent/entity/route / calculation / verification 的确定性行为；
- 可靠性：T608 retry（有界、可重试/不可重试、耗尽）与 timeout（触发/透传）；
- 图级：T609 Research QA happy / no evidence / provider timeout / provider
  conflict / calculation failure / policy block / verification failure；
- T607 checkpoint（InMemorySaver 持久化）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from finsage.agents.research_qa.graph import build_research_qa
from finsage.exceptions import (
    CalculationError,
    NoEvidenceError,
    ProviderDataConflictError,
    ProviderTimeoutError,
)
from finsage.governance.audit import InMemoryAuditSink
from finsage.models.claims import Claim, ResearchAnswer
from finsage.models.entities import Entity
from finsage.models.sources import Evidence, SourceRef
from finsage.providers.finance.domain import FinancialMetric
from finsage.workflows.nodes import (
    WorkflowDeps,
    choose_route,
    classify_intent,
    extract_entities,
    make_verification,
)
from finsage.workflows.reliability import (
    RetryPolicy,
    state_aware_retry,
    with_retry,
    with_timeout,
)

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def make_evidence(eid: str = "ev1", text: str = "公司营收同比增长") -> Evidence:
    return Evidence(
        id=eid,
        document_id="d1",
        chunk_id="c1",
        source=SourceRef(
            source_id=eid,
            title="季度报告",
            retrieved_at=datetime.now(),
            authority_tier=1,
        ),
        text=text,
        relevance_score=0.9,
        authority_score=0.9,
    )


def make_metric(
    metric: str, value: str, period: str = "2023", ptype: str = "FY"
) -> FinancialMetric:
    return FinancialMetric(
        company="腾讯",
        ticker="00700",
        market="HK",
        metric=metric,
        value=Decimal(value),
        currency="CNY",
        unit="CNY_yi",
        period=period,
        period_type=ptype,  # type: ignore[arg-type]  # pydantic 校验 Literal
        source="fake",
        retrieved_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# 1. 节点确定性
# ---------------------------------------------------------------------------


def test_classify_intent_default_fact():
    assert classify_intent("业务模式如何") == "FACT"


def test_classify_intent_numeric():
    assert classify_intent("营收多少") == "NUMERIC"


def test_extract_entities_ticker_with_market():
    ents = extract_entities("对比 AAPL.US 与 MSFT.US 的营收")
    tickers = {e.value for e in ents if e.type == "ticker"}
    assert tickers == {"AAPL", "MSFT"}


def test_extract_entities_company_fallback():
    ents = extract_entities("美团公司的业务")
    assert any(e.type == "company" for e in ents)


def test_extract_entities_cn_numeric_ticker():
    """§2.5：A 股 6 位数字代码应被识别为 ticker（CN）。"""
    ents = extract_entities("评估300750的营收增长")
    tickers = [e for e in ents if e.type == "ticker"]
    assert len(tickers) == 1
    assert tickers[0].value == "300750"
    assert tickers[0].market == "CN"


def test_extract_entities_ignores_4_digit_year():
    """4 位数字（如年份 2024）不应被误判为 6 位 ticker。"""
    ents = extract_entities("评估宁德时代2024年营收")
    assert not any(e.type == "ticker" for e in ents)


def test_make_entity_merges_request_entities():
    """§2.5：请求预置实体（company/ticker）与查询抽取实体合并，不覆盖。"""
    from finsage.workflows.nodes import make_entity

    node = make_entity(WorkflowDeps())
    state = {
        "query": "评估宁德时代2024年营收增长",
        "entities": [
            Entity(type="ticker", value="300750", normalized_value="300750", market="CN"),
            Entity(type="company", value="宁德时代", normalized_value="宁德时代", market="CN"),
        ],
    }
    out = node(state)
    types = {(e.type, e.value) for e in out["entities"]}
    assert ("ticker", "300750") in types
    assert ("company", "宁德时代") in types


def test_choose_route_policy_block():
    assert choose_route({"policy_status": "block"}) == "ABSTAIN"


def test_choose_route_financial_when_numeric_ticker():
    state = {
        "intent": "NUMERIC",
        "entities": [Entity(type="ticker", value="00700", normalized_value="00700", market="HK")],
    }
    assert choose_route(state) == "FINANCIAL_MCP"


def test_choose_route_rag_when_fact():
    state = {"intent": "FACT", "entities": [Entity(type="company", value="美团公司")]}
    assert choose_route(state) == "RAG"


def test_verification_node_fails_on_unresolved_citation():
    claim = Claim(id="c1", text="x", claim_type="fact", evidence_ids=["missing"], confidence=0.5)
    out = make_verification(WorkflowDeps())(
        {"claims": [claim], "evidences": [], "calculations": [], "policy_status": "allow"}
    )
    assert out["error_code"] == "FIN-4101"
    assert out["verification_result"].status == "FAIL"


# ---------------------------------------------------------------------------
# 2. 可靠性（T608 retry / timeout）
# ---------------------------------------------------------------------------


def test_retry_recovers_after_transient():
    calls = {"n": 0}

    def node(state: dict) -> dict:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderTimeoutError("timeout")
        return {"evidences": ["ok"]}

    wrapped = with_retry(node, RetryPolicy(max_attempts=5, base_delay=0))
    out = wrapped({})
    assert out == {"evidences": ["ok"]}
    assert calls["n"] == 3


def test_retry_exhausts():
    calls = {"n": 0}

    def node(state: dict) -> dict:
        calls["n"] += 1
        raise ProviderTimeoutError("timeout")

    wrapped = with_retry(node, RetryPolicy(max_attempts=2, base_delay=0))
    with pytest.raises(ProviderTimeoutError):
        wrapped({})
    assert calls["n"] == 2


def test_retry_does_not_retry_non_retryable():
    calls = {"n": 0}

    def node(state: dict) -> dict:
        calls["n"] += 1
        raise CalculationError("bad calc")

    wrapped = with_retry(node, RetryPolicy(max_attempts=5, base_delay=0))
    with pytest.raises(CalculationError):
        wrapped({})
    assert calls["n"] == 1  # 非重试错误码不再尝试


def test_state_aware_retry_retries_retryable_error_code():
    """P1：节点把错误码写回 state（而非抛异常）时，重试也应触发。"""
    calls = {"n": 0}

    async def node(state: dict) -> dict:
        calls["n"] += 1
        if calls["n"] < 3:
            return {"error_code": "FIN-2001"}  # PROVIDER_TIMEOUT 可重试
        return {"evidences": ["ok"]}

    wrapped = state_aware_retry(node, RetryPolicy(max_attempts=5, base_delay=0))
    out = asyncio.run(wrapped({}))
    assert out == {"evidences": ["ok"]}
    assert calls["n"] == 3


def test_state_aware_retry_exhausts():
    calls = {"n": 0}

    async def node(state: dict) -> dict:
        calls["n"] += 1
        return {"error_code": "FIN-2001"}

    wrapped = state_aware_retry(node, RetryPolicy(max_attempts=2, base_delay=0))
    out = asyncio.run(wrapped({}))
    assert out["error_code"] == "FIN-2001"
    assert calls["n"] == 2


def test_state_aware_retry_non_retryable_code_returns_immediately():
    calls = {"n": 0}

    async def node(state: dict) -> dict:
        calls["n"] += 1
        return {"error_code": "FIN-1004"}  # 不可重试

    wrapped = state_aware_retry(node, RetryPolicy(max_attempts=5, base_delay=0))
    out = asyncio.run(wrapped({}))
    assert out["error_code"] == "FIN-1004"
    assert calls["n"] == 1


async def test_timeout_triggers_error_code():
    async def slow_node(state: dict) -> dict:
        await asyncio.sleep(0.2)
        return {"evidences": ["ok"]}

    wrapped = with_timeout(slow_node, 0.05)
    out = await wrapped({})
    assert out == {"error_code": "FIN-5002"}


def test_timeout_passthrough_when_non_positive():
    def node(state: dict) -> dict:
        return {"evidences": ["ok"]}

    assert with_timeout(node, 0) is node  # 非正阈值原样透传


async def test_timeout_allows_fast_node():
    async def fast_node(state: dict) -> dict:
        return {"evidences": ["ok"]}

    wrapped = with_timeout(fast_node, 1.0)
    out = await wrapped({})
    assert out == {"evidences": ["ok"]}


# ---------------------------------------------------------------------------
# 3. 图级 Research QA（T609）
# ---------------------------------------------------------------------------


async def _retrieve_evidence(q, plan, *, tenant_id=None):
    return [make_evidence()]


async def _retrieve_none(q, plan, *, tenant_id=None):
    raise NoEvidenceError("no evidence found")


async def test_graph_happy_path_answer():
    deps = WorkflowDeps(retrieve=_retrieve_evidence)
    graph = build_research_qa(deps)
    out = await graph.ainvoke(
        {"query": "美团公司的业务模式是什么", "request_id": "r1", "trace_id": "t1"}
    )
    assert out.get("error_code") is None
    assert isinstance(out["final_answer"], ResearchAnswer)
    # §24 六因素置信度已接线：不再硬编码 0.9，而是由证据/计算/校验确定性推导。
    assert out["confidence"] != 0.9
    assert out["final_answer"].confidence == out["confidence"]
    assert out["final_answer"].claims  # 有论断产出


async def test_graph_no_evidence_abstains():
    deps = WorkflowDeps(retrieve=_retrieve_none)
    graph = build_research_qa(deps)
    out = await graph.ainvoke(
        {"query": "美团公司的业务模式是什么", "request_id": "r1", "trace_id": "t1"}
    )
    assert out["error_code"] == "FIN-3003"
    assert out["confidence"] == 0.0
    assert any("abstained" in w for w in out["warnings"])


async def test_graph_financial_mcp_calculates_and_answers():
    async def financial(q, entities):
        return [make_metric("revenue", "100"), make_metric("net_income", "20")]

    deps = WorkflowDeps(financial=financial)
    graph = build_research_qa(deps)
    out = await graph.ainvoke(
        {"query": "00700.HK 营收和净利润多少", "request_id": "r1", "trace_id": "t1"}
    )
    assert isinstance(out["final_answer"], ResearchAnswer)
    assert out["final_answer"].calculations


async def test_graph_provider_timeout_abstains():
    async def financial(q, entities):
        raise ProviderTimeoutError("upstream timeout")

    deps = WorkflowDeps(financial=financial)
    graph = build_research_qa(deps)
    out = await graph.ainvoke({"query": "00700.HK 营收多少", "request_id": "r1", "trace_id": "t1"})
    assert out["error_code"] == "FIN-2001"
    assert out["confidence"] == 0.0


async def test_graph_provider_conflict_abstains():
    async def financial(q, entities):
        raise ProviderDataConflictError("conflict")

    deps = WorkflowDeps(financial=financial)
    graph = build_research_qa(deps)
    out = await graph.ainvoke({"query": "00700.HK 营收多少", "request_id": "r1", "trace_id": "t1"})
    assert out["error_code"] == "FIN-2101"
    assert out["confidence"] == 0.0


async def test_graph_calculation_failure_abstains():
    async def financial(q, entities):
        return [make_metric("revenue", "100")]

    def bad_calc(financial_data):
        raise CalculationError("divide by zero")

    deps = WorkflowDeps(financial=financial, calc_runner=bad_calc)
    graph = build_research_qa(deps)
    out = await graph.ainvoke({"query": "00700.HK 财务数据", "request_id": "r1", "trace_id": "t1"})
    assert out["error_code"] == "FIN-3101"
    assert out["confidence"] == 0.0


async def test_graph_policy_block_abstains():
    graph = build_research_qa(WorkflowDeps())
    # "建议买入" 命中投资建议边界 -> policy block -> route ABSTAIN。
    out = await graph.ainvoke({"query": "建议买入 00700.HK", "request_id": "r1", "trace_id": "t1"})
    assert out["policy_status"] == "block"
    assert out["error_code"] == "FIN-4001"
    assert out["confidence"] == 0.0


async def test_graph_audit_recorded():
    sink = InMemoryAuditSink()
    deps = WorkflowDeps(retrieve=_retrieve_evidence, audit=sink)
    graph = build_research_qa(deps)
    await graph.ainvoke({"query": "美团公司的业务模式是什么", "request_id": "r1", "trace_id": "t1"})
    assert sink.entries  # 至少一条审计记录落盘


# ---------------------------------------------------------------------------
# 4. T607 checkpoint
# ---------------------------------------------------------------------------


async def test_checkpoint_persists_state_across_runs():
    deps = WorkflowDeps(retrieve=_retrieve_evidence)
    saver = InMemorySaver()
    graph = build_research_qa(deps, checkpointer=saver)

    config = {"configurable": {"thread_id": "thread-1"}}
    out = await graph.ainvoke({"query": "美团公司的业务模式是什么"}, config=config)
    assert isinstance(out["final_answer"], ResearchAnswer)
    snapshot = saver.get(config)
    assert snapshot is not None  # 已完成运行已写入 checkpoint