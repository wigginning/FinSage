"""m06 T604/T605/T606 三张图（§18/§19/§20）验收测试。

覆盖（§28.4/T609，每图各自 happy / 退化路径）：
- §18 Financial Health：happy path（产生健康度报告）、cross_check 冲突 -> FIN-2101、
  provider timeout -> FIN-2001、policy block -> FIN-4001；
- §19 Due Diligence：八阶段顺序落地、范本报告组装、无证据时 verification ABSTAIN
  但报告保留；
- §20 Report：有证据/计算时组装出含各章节的报告、verify PASS；无输入时 verify ABSTAIN。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest  # noqa: F401  # pytest.raises 供退化路径扩展

from finsage.agents.due_diligence.graph import (
    DUE_DILIGENCE_PHASES,
    build_due_diligence,
)
from finsage.agents.financial_health.graph import build_financial_health
from finsage.agents.report.graph import build_report
from finsage.exceptions import ProviderTimeoutError
from finsage.models.claims import Claim, ResearchAnswer
from finsage.models.entities import Entity
from finsage.models.sources import Evidence, SourceRef
from finsage.providers.finance.domain import FinancialMetric
from finsage.workflows.nodes import WorkflowDeps


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


def make_metric(metric: str, value: str, period: str = "2023") -> FinancialMetric:
    return FinancialMetric(
        company="腾讯",
        ticker="00700",
        market="HK",
        metric=metric,
        value=Decimal(value),
        currency="CNY",
        unit="CNY_yi",
        period=period,
        period_type="FY",
        source="fake",
        retrieved_at=datetime.now(),
    )


async def _healthy_financial(query: str, entities: list[Entity]) -> list[FinancialMetric]:
    # 净利率 25/100=25% > 20% 阈值，明确落在 healthy，避开 0.20 浮点边界。
    return [make_metric("revenue", "100"), make_metric("net_income", "25")]


# ---------------------------------------------------------------------------
# §18 Financial Health（T604）
# ---------------------------------------------------------------------------


async def test_financial_health_happy_path_report():
    deps = WorkflowDeps(financial=_healthy_financial)
    graph = build_financial_health(deps)
    out = await graph.ainvoke(
        {
            "query": "00700.HK 财务健康度如何",
            "request_id": "r1",
            "trace_id": "t1",
        }
    )
    assert out.get("error_code") is None
    assert isinstance(out["final_answer"], ResearchAnswer)
    assert out["health_status"] == "healthy"
    assert out["final_answer"].calculations
    assert "财务健康分析" in out["final_answer"].answer


async def test_financial_health_cross_check_conflict_abstains():
    async def conflict(q: str, entities: list[Entity]) -> list[FinancialMetric]:
        # 仅有 revenue，无 net_income -> 无法派生净利率计算 -> 交叉核对冲突。
        return [make_metric("revenue", "100")]

    deps = WorkflowDeps(financial=conflict)
    graph = build_financial_health(deps)
    out = await graph.ainvoke({"query": "00700.HK 财务健康度如何"})
    assert out["error_code"] == "FIN-2101"
    assert out["final_answer"].confidence == 0.0


async def test_financial_health_provider_timeout_abstains():
    async def timeout(q: str, entities: list[Entity]) -> list[FinancialMetric]:
        raise ProviderTimeoutError("timeout")

    deps = WorkflowDeps(financial=timeout)
    graph = build_financial_health(deps)
    out = await graph.ainvoke({"query": "00700.HK 财务健康度如何"})
    assert out["error_code"] == "FIN-2001"
    assert out["final_answer"].confidence == 0.0
    assert any("abstained:FIN-2001" in w for w in out["final_answer"].warnings)


async def test_financial_health_policy_block_abstains():
    deps = WorkflowDeps(financial=_healthy_financial)
    graph = build_financial_health(deps)
    out = await graph.ainvoke({"query": "00700.HK 建议买入吗"})
    assert out["error_code"] == "FIN-4001"
    assert out["final_answer"].confidence == 0.0


# ---------------------------------------------------------------------------
# §19 Due Diligence（T605）
# ---------------------------------------------------------------------------


def test_due_diligence_phases_frozen_order():
    # §19 阶段顺序（§16 No-Guess：不增删、不调序）。
    assert DUE_DILIGENCE_PHASES == (
        "WARMUP",
        "COMPANY_PROFILE",
        "BUSINESS_MODEL",
        "FINANCIALS",
        "COMPETITION",
        "RISK",
        "RED_FLAGS",
        "FOLLOW_UP",
    )


async def test_due_diligence_happy_path_report():
    graph = build_due_diligence()
    out = await graph.ainvoke(
        {
            "query": "尽调美团公司",
            "entities": [Entity(type="company", value="美团公司", normalized_value="美团公司")],
            "evidences": [make_evidence()],
        }
    )
    assert out.get("error_code") is None
    # 八个阶段全部落地进 dossier。
    assert set(DUE_DILIGENCE_PHASES).issubset(set(out["dossier"].keys()))
    # 有证据、无未解析论断 -> PASS。
    assert out["verification_result"].status == "PASS"
    assert isinstance(out["final_answer"], ResearchAnswer)
    # 报告正文包含各阶段确定性分析片段。
    assert "美团公司" in out["final_answer"].answer
    assert "后续事项" in out["final_answer"].answer


async def test_due_diligence_no_evidence_abstains_but_keeps_report():
    graph = build_due_diligence()
    out = await graph.ainvoke({"query": "尽调美团公司"})
    # 无证据/论断 -> verification ABSTAIN，但仍产出范本报告，且不置 FAIL 错误。
    assert out["verification_result"].status == "ABSTAIN"
    assert out.get("error_code") is None
    assert out["final_answer"].answer


# ---------------------------------------------------------------------------
# §20 Report（T606）
# ---------------------------------------------------------------------------


async def test_report_happy_path_assembles_sections():
    graph = build_report()
    out = await graph.ainvoke(
        {
            "query": "生成研究报告",
            "research_run": {"run_id": "run-1"},
            "evidences": [make_evidence("ev-a", "营收高增长")],
            "calculations": [],
        }
    )
    assert out.get("error_code") is None
    assert out["verification_result"].status == "PASS"
    assert isinstance(out["final_answer"], ResearchAnswer)
    for heading in ("## 摘要", "## 证据", "## 计算", "## 论断"):
        assert heading in out["final_answer"].answer


async def test_report_no_input_abstains():
    graph = build_report()
    out = await graph.ainvoke({"query": "生成研究报告"})
    # 全空输入 -> V008 ABSTAIN；仍产出（空）报告，不置 FAIL。
    assert out["verification_result"].status == "ABSTAIN"
    assert out.get("error_code") is None


# ---------------------------------------------------------------------------
# ADR-0017：治理短路（V009/V010）+ §24 置信度接线 回归
# ---------------------------------------------------------------------------


def _unresolved_claim() -> Claim:
    """引用不存在证据的论断 —— 触发 V003 -> FAIL。"""
    return Claim(
        id="c1",
        text="悬空引用论断",
        claim_type="fact",
        evidence_ids=["ghost-ev"],
        confidence=0.9,
    )


async def test_due_diligence_policy_block_abstains_no_report():
    """V009：政策拦截 -> 不进入八阶段机、不产出报告。"""
    graph = build_due_diligence()
    out = await graph.ainvoke(
        {
            "query": "建议买入美团公司",
            "entities": [Entity(type="company", value="美团公司", normalized_value="美团公司")],
        }
    )
    assert out["error_code"] == "FIN-4001"
    assert out["final_answer"].confidence == 0.0
    # 阶段机未被进入：dossier 为空。
    assert not out.get("dossier")
    assert "美团公司" not in out["final_answer"].answer


async def test_due_diligence_verification_fail_abstains_no_report():
    """V010：校验 FAIL -> 不保留报告正文。"""
    graph = build_due_diligence()
    out = await graph.ainvoke(
        {
            "query": "尽调美团公司",
            "entities": [Entity(type="company", value="美团公司", normalized_value="美团公司")],
            "evidences": [make_evidence()],
            "claims": [_unresolved_claim()],
        }
    )
    assert out["verification_result"].status == "FAIL"
    assert out["error_code"] == "FIN-4101"
    assert out["final_answer"].confidence == 0.0
    # 报告正文被弃权文案取代（不再"FAIL 仍发报告"）。
    assert "后续事项" not in out["final_answer"].answer


async def test_due_diligence_confidence_not_hardcoded():
    """§24：DD 图置信度由六因素推导，不再是硬编码 0.9。"""
    graph = build_due_diligence()
    out = await graph.ainvoke(
        {
            "query": "尽调美团公司",
            "entities": [Entity(type="company", value="美团公司", normalized_value="美团公司")],
            "evidences": [make_evidence()],
        }
    )
    confidence = out["final_answer"].confidence
    assert 0.0 < confidence < 1.0
    assert confidence != 0.9
    assert confidence == out["confidence"]


async def test_report_verification_fail_abstains():
    """V010：Report 图校验 FAIL -> 不组装报告。"""
    graph = build_report()
    out = await graph.ainvoke(
        {
            "query": "生成研究报告",
            "research_run": {"run_id": "run-1"},
            "evidences": [make_evidence("ev-a", "营收高增长")],
            "claims": [_unresolved_claim()],
        }
    )
    assert out["verification_result"].status == "FAIL"
    assert out["error_code"] == "FIN-4101"
    assert out["final_answer"].confidence == 0.0
    assert "## 摘要" not in out["final_answer"].answer


async def test_report_policy_block_abstains():
    """V009：Report 图透传 policy_status（原硬编码 None 使 V009 永不触发）。"""
    graph = build_report()
    out = await graph.ainvoke(
        {
            "query": "生成研究报告",
            "policy_status": "block",
            "evidences": [make_evidence("ev-a", "营收高增长")],
        }
    )
    assert out["verification_result"].status == "FAIL"
    assert "V009" in out["verification_result"].failed_rules
    assert out["error_code"] == "FIN-4101"
    assert out["final_answer"].confidence == 0.0


async def test_report_confidence_not_hardcoded():
    graph = build_report()
    out = await graph.ainvoke(
        {
            "query": "生成研究报告",
            "research_run": {"run_id": "run-1"},
            "evidences": [make_evidence("ev-a", "营收高增长")],
        }
    )
    confidence = out["final_answer"].confidence
    assert 0.0 < confidence < 1.0
    assert confidence != 0.9


def test_calc_claim_confidence_bounded_by_evidence_binding():
    """计算型论断置信度反映可溯源性（不再硬编码 0.9）。"""
    from finsage.financial.models import Calculation
    from finsage.workflows.nodes import _calc_claim_confidence

    bound = Calculation(
        formula="a/b",
        inputs={"a": Decimal("1"), "b": Decimal("4")},
        output_value=Decimal("0.25"),
        source_evidence_ids=["ev1"],
    )
    unbound = bound.model_copy(update={"source_evidence_ids": []})
    ev = make_evidence("ev1")

    assert _calc_claim_confidence(bound, [ev]) == 0.9
    assert _calc_claim_confidence(unbound, [ev]) == 0.5
    # 引用不存在的证据 id -> 等同未绑定，不冒充高置信。
    dangling = bound.model_copy(update={"source_evidence_ids": ["ghost"]})
    assert _calc_claim_confidence(dangling, [ev]) == 0.5


async def test_audit_sink_failure_does_not_break_workflow():
    """P0：审计 sink 故障不得拖垮已算完的主流程。"""

    class _BrokenAuditSink:
        def record(self, entry: object) -> None:
            raise RuntimeError("audit db down")

    from finsage.workflows.nodes import make_audit

    node = make_audit(WorkflowDeps(audit=_BrokenAuditSink()))
    out = node({"trace_id": "t1", "final_answer": None})
    assert out["audit_id"]