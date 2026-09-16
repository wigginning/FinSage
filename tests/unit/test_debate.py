"""ADR-0009 多空辩论节点测试（F4 不确定性显式化）。

覆盖：
- ``arbitrate_debate`` 确定性仲裁：分歧度（Jaccard 距离）与 verdict；
- ``make_debate`` 节点：确定性推导（bull 回显 / bear 质疑弱论断）；
- 图级：Research QA happy path 产出 debate_result 并写入 final_answer.disagreement，
  以及 no-evidence failure path 仍弃权。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from finsage.agents.research_qa.graph import build_research_qa
from finsage.models.claims import Claim, ResearchAnswer
from finsage.models.debate import (
    DebateArgument,
    DebateArgumentDraft,
    DebateArgumentsResponse,
    DebateResult,
)
from finsage.models.sources import Evidence, SourceRef
from finsage.workflows.nodes import WorkflowDeps, _llm_arguments, arbitrate_debate, make_debate


def make_claim(
    cid: str = "c1",
    text: str = "营收同比增长",
    evidence_ids: list[str] | None = None,
    confidence: float = 0.9,
) -> Claim:
    return Claim(
        id=cid,
        text=text,
        claim_type="fact",
        evidence_ids=evidence_ids or [],
        confidence=confidence,
    )


def make_evidence(eid: str = "ev1") -> Evidence:
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
        text="公司营收同比增长",
        relevance_score=0.9,
        authority_score=0.9,
    )


# ---------------------------------------------------------------------------
# 1. arbitrate_debate 确定性仲裁
# ---------------------------------------------------------------------------


def test_arbitrate_empty_is_insufficient():
    result = arbitrate_debate([], [])
    assert result.verdict == "insufficient"
    assert result.disagreement == 0.0


def test_arbitrate_bull_only_no_disagreement():
    bull = [DebateArgument(side="bull", text="支持", evidence_ids=["ev1"], confidence=0.9)]
    result = arbitrate_debate(bull, [])
    assert result.verdict == "bull"
    assert result.disagreement == 0.0


def test_arbitrate_bear_only_full_disagreement():
    bear = [DebateArgument(side="bear", text="质疑", evidence_ids=[], confidence=0.8)]
    result = arbitrate_debate([], bear)
    assert result.verdict == "bear"
    assert result.disagreement == 1.0


def test_arbitrate_disjoint_evidence_full_disagreement():
    bull = [DebateArgument(side="bull", text="支持", evidence_ids=["ev1"], confidence=0.9)]
    bear = [DebateArgument(side="bear", text="质疑", evidence_ids=["ev2"], confidence=0.9)]
    result = arbitrate_debate(bull, bear)
    assert result.disagreement == 1.0


def test_arbitrate_overlapping_evidence_partial_disagreement():
    bull = [DebateArgument(side="bull", text="支持", evidence_ids=["ev1", "ev2"], confidence=0.9)]
    bear = [DebateArgument(side="bear", text="质疑", evidence_ids=["ev2"], confidence=0.9)]
    result = arbitrate_debate(bull, bear)
    # 交集 {ev2} / 并集 {ev1, ev2} = 0.5 -> disagreement 0.5
    assert result.disagreement == 0.5


def test_arbitrate_balanced_verdict():
    bull = [DebateArgument(side="bull", text="支持", evidence_ids=["ev1"], confidence=0.8)]
    bear = [DebateArgument(side="bear", text="质疑", evidence_ids=["ev2"], confidence=0.8)]
    result = arbitrate_debate(bull, bear)
    assert result.verdict == "balanced"


# ---------------------------------------------------------------------------
# 2. make_debate 节点（确定性推导）
# ---------------------------------------------------------------------------


def test_debate_node_bull_echoes_claim():
    node = make_debate(WorkflowDeps())
    claim = make_claim(evidence_ids=["ev1"], confidence=0.9)
    out = node({"claims": [claim], "evidences": [make_evidence("ev1")]})
    result: DebateResult = out["debate_result"]
    assert result.verdict == "bull"
    assert result.disagreement == 0.0
    assert len(result.bull_arguments) == 1
    assert result.bull_arguments[0].evidence_ids == ["ev1"]
    assert result.bear_arguments == []  # 高置信且有证据 -> 空方无反对


def test_debate_node_bear_challenges_weak_claim():
    node = make_debate(WorkflowDeps())
    claim = make_claim(evidence_ids=[], confidence=0.3)
    out = node({"claims": [claim], "evidences": []})
    result: DebateResult = out["debate_result"]
    assert len(result.bear_arguments) == 1
    assert result.bear_arguments[0].confidence == pytest.approx(0.7)
    assert result.bear_arguments[0].evidence_ids == []


def test_debate_node_no_claims_is_insufficient():
    node = make_debate(WorkflowDeps())
    out = node({"claims": [], "evidences": []})
    assert out["debate_result"].verdict == "insufficient"


# ---------------------------------------------------------------------------
# 2b. LLM 结构化增强（ADR-0012 complete_typed）
# ---------------------------------------------------------------------------


class _FakeTypedLLM:
    """实现 complete_typed 的 fake LLM（返回固定 DebateArgumentsResponse）。"""

    name = "fake-typed"

    def __init__(self, response: DebateArgumentsResponse | None):
        self._response = response

    def complete(self, *, system: str, prompt: str) -> str:
        return ""

    def complete_structured(self, *, system: str, prompt: str) -> str:
        return ""

    def complete_typed(self, *, system: str, prompt: str, schema):
        if self._response is None:
            raise NotImplementedError("no structured output")
        return self._response


def test_llm_arguments_typed_enrichment():
    resp = DebateArgumentsResponse(
        arguments=[DebateArgumentDraft(text="LLM 论点", evidence_ids=["ev1"], confidence=0.8)]
    )
    args = _llm_arguments("bull", [make_claim(evidence_ids=["ev1"])], {"ev1"}, _FakeTypedLLM(resp))
    assert len(args) == 1
    assert args[0].side == "bull"
    assert args[0].text == "LLM 论点"
    assert args[0].evidence_ids == ["ev1"]
    assert args[0].confidence == 0.8


def test_llm_arguments_downgrades_unsourced_numeric():
    resp = DebateArgumentsResponse(
        arguments=[DebateArgumentDraft(text="数值声明", evidence_ids=["missing"], confidence=0.8)]
    )
    args = _llm_arguments("bear", [make_claim()], {"ev1"}, _FakeTypedLLM(resp))
    assert args[0].evidence_ids == []  # 未挂真实来源 -> 清空引用
    assert args[0].confidence == 0.4  # 置信度减半


def test_llm_arguments_falls_back_on_error():
    args = _llm_arguments("bull", [make_claim()], set(), _FakeTypedLLM(None))
    assert args is None  # complete_typed 抛错 -> 回退确定性推导


# ---------------------------------------------------------------------------
# 3. 图级（Research QA）
# ---------------------------------------------------------------------------


async def _retrieve_evidence(q, plan, *, tenant_id=None):
    return [make_evidence("ev1")]


async def test_graph_happy_path_sets_disagreement():
    deps = WorkflowDeps(retrieve=_retrieve_evidence)
    graph = build_research_qa(deps)
    out = await graph.ainvoke(
        {"query": "美团公司的业务模式是什么", "request_id": "r1", "trace_id": "t1"}
    )
    assert out.get("error_code") is None
    assert isinstance(out["final_answer"], ResearchAnswer)
    assert isinstance(out["debate_result"], DebateResult)
    # 高置信有证据 -> 无空方反对 -> disagreement 0.0
    assert out["final_answer"].disagreement == 0.0


async def test_graph_no_evidence_still_abstains():
    from finsage.exceptions import NoEvidenceError

    async def retrieve_none(q, plan, *, tenant_id=None):
        raise NoEvidenceError("no evidence")

    deps = WorkflowDeps(retrieve=retrieve_none)
    graph = build_research_qa(deps)
    out = await graph.ainvoke(
        {"query": "美团公司的业务模式是什么", "request_id": "r1", "trace_id": "t1"}
    )
    assert out["error_code"] == "FIN-3003"
    assert out["confidence"] == 0.0
    # 弃权路径不产出 final_answer，但 debate 节点仍运行（insufficient）。
    assert out["debate_result"].verdict == "insufficient"
