"""ADR-0018 能力闭环回归测试（估值引擎 / 情绪管线 / 分歧度下发）。

背景：审计（2026-08-26）确认 ``financial/valuation.py``、``sentiment.py``
与 ``ResearchAnswer.disagreement`` 三块已 Accepted 的能力"实现了、测过了，
但没有任何请求路径可达"。本文件冻结接线后的行为契约。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from finsage.models.claims import Claim, ResearchAnswer, SentimentSummary
from finsage.models.sources import Evidence, SourceRef
from finsage.providers.finance.domain import FinancialMetric
from finsage.settings import Settings
from finsage.workflows.nodes import (
    WorkflowDeps,
    _valuation_calculations,
    is_valuation_query,
    make_answer,
    make_calculation,
    make_sentiment,
)


def make_metric(
    metric: str, value: str, period: str, *, market: str = "CN", ticker: str = "600519"
) -> FinancialMetric:
    return FinancialMetric(
        company="贵州茅台",
        ticker=ticker,
        market=market,
        metric=metric,
        value=Decimal(value),
        currency="CNY",
        unit="CNY_yi",
        period=period,
        period_type="FY",
        source="fake",
        retrieved_at=datetime.now(),
    )


def make_evidence(eid: str = "ev1", text: str = "营收增长") -> Evidence:
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


# ---------------------------------------------------------------------------
# A2 估值引擎接线
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query", ["贵州茅台估值多少", "做一下 DCF 折现", "内在价值区间", "enterprise valuation"]
)
def test_is_valuation_query_detects_valuation(query: str) -> None:
    assert is_valuation_query(query) is True


@pytest.mark.parametrize("query", ["贵州茅台营收多少", "财务健康度如何", ""])
def test_is_valuation_query_rejects_non_valuation(query: str) -> None:
    assert is_valuation_query(query) is False


def test_valuation_projects_growth_from_real_history() -> None:
    """增长率外推用历史真实增速（100 -> 150 即 +50%），不臆造增长率。"""
    data = [make_metric("revenue", "100", "2022"), make_metric("revenue", "150", "2023")]
    calcs, warnings = _valuation_calculations(data, [])
    assert len(calcs) == 1
    calc = calcs[0]
    assert "project_growth(revenue" in calc.formula
    # g=0.5，外推 3 期：150 * 1.5^3 = 506.25
    assert calc.output_value == Decimal("506.25")
    assert calc.inputs["growth_rate"] == Decimal("0.5")
    assert warnings == []


def test_valuation_skips_growth_when_history_insufficient() -> None:
    """历史不足两期 -> 跳过，绝不臆造增长率。"""
    calcs, _ = _valuation_calculations([make_metric("revenue", "100", "2023")], [])
    assert calcs == []


def test_valuation_dcf_skipped_without_configured_assumptions() -> None:
    """未配置 WACC/永续增长率 -> 跳过 DCF 并记 warning，不套用"行业惯例默认值"。"""
    data = [
        make_metric("free_cash_flow", "100", "2022"),
        make_metric("free_cash_flow", "120", "2023"),
    ]
    calcs, warnings = _valuation_calculations(data, [])
    assert all("dcf(" not in c.formula for c in calcs)
    assert "dcf_skipped:valuation_assumptions_not_configured" in warnings


def test_valuation_dcf_computed_when_assumptions_configured(monkeypatch) -> None:
    """显式配置假设后才计算 DCF（假设来自配置，引擎不背书）。"""
    configured = Settings(
        _env_file=None,
        valuation_wacc=Decimal("0.10"),
        valuation_terminal_growth=Decimal("0.03"),
    )
    monkeypatch.setattr("finsage.settings.get_settings", lambda: configured)

    data = [
        make_metric("free_cash_flow", "100", "2022"),
        make_metric("free_cash_flow", "120", "2023"),
    ]
    calcs, warnings = _valuation_calculations(data, [])
    dcf_calcs = [c for c in calcs if c.formula.startswith("dcf(")]
    assert len(dcf_calcs) == 1
    assert dcf_calcs[0].inputs["wacc"] == Decimal("0.10")
    assert "dcf_skipped" not in "".join(warnings)


def test_calculation_node_appends_valuation_for_valuation_query() -> None:
    """估值类查询经 make_calculation 产出估值计算（此前无任何请求路径可达）。"""
    deps = WorkflowDeps()
    node = make_calculation(deps)
    out = node(
        {
            "query": "贵州茅台估值多少",
            "financial_data": [
                make_metric("revenue", "100", "2022"),
                make_metric("revenue", "150", "2023"),
            ],
            "evidences": [],
        }
    )
    assert any("project_growth(revenue" in c.formula for c in out["calculations"])


def test_calculation_node_leaves_non_valuation_query_unchanged() -> None:
    """非估值查询不得凭空多出估值计算。"""
    deps = WorkflowDeps()
    node = make_calculation(deps)
    out = node(
        {
            "query": "贵州茅台营收多少",
            "financial_data": [
                make_metric("revenue", "100", "2023"),
                make_metric("net_income", "25", "2023"),
            ],
            "evidences": [],
        }
    )
    assert all("project_growth" not in c.formula for c in out["calculations"])
    assert "warnings" not in out


# ---------------------------------------------------------------------------
# A3 情绪管线接线
# ---------------------------------------------------------------------------


def test_sentiment_node_aggregates_evidence() -> None:
    node = make_sentiment(WorkflowDeps())
    out = node(
        {
            "evidences": [
                make_evidence("ev1", "营收增长，净利润创新高"),
                make_evidence("ev2", "因违规被立案调查，存在退市风险"),
            ]
        }
    )
    summary = out["sentiment_summary"]
    assert isinstance(summary, SentimentSummary)
    assert summary.analyzed == 2
    assert summary.positive == 1
    assert summary.negative == 1
    # 规则法未校准：契约要求恒为 False，呈现层必须标注。
    assert summary.calibrated is False
    assert summary.method == "keyword_rule_based"


def test_sentiment_node_none_without_evidence() -> None:
    """无证据不伪造"中性"结论，返回 None。"""
    node = make_sentiment(WorkflowDeps())
    assert node({"evidences": []})["sentiment_summary"] is None


# ---------------------------------------------------------------------------
# A1 分歧度 / 情绪聚合进入最终答案
# ---------------------------------------------------------------------------


def test_answer_node_carries_disagreement_and_sentiment() -> None:
    """两者此前在 answer_node 之外被组装逻辑丢弃，前端零消费。"""

    class _Debate:
        disagreement = 0.42

    node = make_answer(WorkflowDeps())
    out = node(
        {
            "draft_answer": "结论文本",
            "debate_result": _Debate(),
            "sentiment_summary": SentimentSummary(analyzed=1, positive=1, mean_score=1.0),
            "evidences": [make_evidence()],
            "claims": [
                Claim(
                    id="c1",
                    text="x",
                    claim_type="fact",
                    evidence_ids=["ev1"],
                    confidence=0.9,
                )
            ],
            "calculations": [],
            "verification_result": None,
        }
    )
    ans: ResearchAnswer = out["final_answer"]
    assert ans.disagreement == 0.42
    assert ans.sentiment_summary is not None
    assert ans.sentiment_summary.analyzed == 1
    assert ans.sentiment_summary.calibrated is False
