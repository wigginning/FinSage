"""P2 冲突检测接线：detect_metric_conflicts + 工作流节点（离线）。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from finsage.providers.finance.conflict import detect_metric_conflicts
from finsage.providers.finance.domain import FinancialMetric
from finsage.workflows.nodes import WorkflowDeps, make_financial_data


def _metric(*, source: str, value: str, period: str = "2024") -> FinancialMetric:
    return FinancialMetric(
        company="茅台",
        ticker="600519",
        market="CN",
        metric="revenue",
        value=Decimal(value),
        currency="CNY",
        unit="CNY_yi",
        period=period,
        period_type="FY",
        source=source,
        retrieved_at=datetime(2026, 8, 26),
    )


def test_detect_conflict_single_source_no_conflict():
    metrics = [_metric(source="akshare", value="100"), _metric(source="akshare", value="100")]
    assert detect_metric_conflicts(metrics) == []


def test_detect_conflict_matching_values_across_sources():
    a = _metric(source="akshare", value="100")
    b = _metric(source="efinance", value="100")
    assert detect_metric_conflicts([a, b]) == []  # MATCH，无冲突


def test_detect_conflict_diverging_values():
    a = _metric(source="akshare", value="100")
    b = _metric(source="efinance", value="500")  # 相对误差远超容差 -> CONFLICT
    conflicts = detect_metric_conflicts([a, b])
    assert len(conflicts) == 1
    assert "CONFLICT:" in conflicts[0]


def test_detect_conflict_different_period_no_cross():
    a = _metric(source="akshare", value="100", period="2024")
    b = _metric(source="efinance", value="100", period="2025")
    assert detect_metric_conflicts([a, b]) == []  # 不同期间不比对


async def test_financial_node_sets_data_conflict_on_divergence():
    """P2：跨 Provider 冲突时 financial_data 节点应置 data_conflict + 告警。"""

    async def fake_financial(q, entities):
        return [_metric(source="akshare", value="100"), _metric(source="efinance", value="500")]

    deps = WorkflowDeps(financial=fake_financial)
    node = make_financial_data(deps)
    out = await node({"normalized_query": "x", "entities": []})
    assert out.get("data_conflict") is True
    assert "provider_data_conflict" in out.get("warnings", [])


async def test_financial_node_no_conflict_no_flag():
    async def fake_financial(q, entities):
        return [_metric(source="akshare", value="100")]

    deps = WorkflowDeps(financial=fake_financial)
    node = make_financial_data(deps)
    out = await node({"normalized_query": "x", "entities": []})
    assert out.get("data_conflict") in (None, False)
    assert "provider_data_conflict" not in (out.get("warnings") or [])
