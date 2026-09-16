"""FinEval 单元测试（m09 T901–T909）。

覆盖：
- 数据集/用例格式映射与回溯（T901）
- 100 条基准结构（T902）
- 五类评估器正确性（T903–T907）
- runner 执行 + 指标聚合 + 落库（T908）
- 可复现性元数据（T909）

不使用真实 DB / 模型 / 网络：executor 用替身，store 用内存实现。
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from finsage.evaluation import (
    TASK_ABSTENTION,
    TASK_CITATION,
    TASK_DECISION,
    TASK_NUMERIC,
    TASK_PROVIDER,
    TASK_RETRIEVAL,
    BenchmarkRunner,
    CaseSpec,
    InMemoryEvaluationStore,
    RunMetadata,
    build_benchmark,
    build_dataset,
    collect_metadata,
    get_evaluator,
)
from finsage.evaluation.dataset import (
    dataset_spec_to_expected_count,
    expected_json,
    from_records,
    tags_json,
)

# ---- T901 数据集/用例格式 ----


def test_case_rejects_unknown_task_type():
    with pytest.raises(ValueError):
        CaseSpec("q", "unknown_task", expected={})


def test_expected_and_tags_json_roundtrip():
    case = CaseSpec("query-1", TASK_NUMERIC,
                    expected={"value": "0.1", "unit": "ratio"},
                    tags={"category": "ratio"})
    rebuilt = from_records(
        query="query-1",
        expected_json_=expected_json(case),
        tags_json_=tags_json(case),
    )
    assert rebuilt.query == "query-1"
    assert rebuilt.task_type == TASK_NUMERIC
    assert rebuilt.expected == {"value": "0.1", "unit": "ratio"}
    assert rebuilt.tags == {"category": "ratio"}


def test_build_dataset_combined_vs_single_type():
    mixed = build_dataset(
        name="d", version="1", cases=[
            CaseSpec("a", TASK_RETRIEVAL), CaseSpec("b", TASK_NUMERIC),
        ],
    )
    assert mixed.task_type == "combined"
    single = build_dataset(
        name="d", version="1", cases=[CaseSpec("a", TASK_NUMERIC), CaseSpec("b", TASK_NUMERIC)],
    )
    assert single.task_type == TASK_NUMERIC
    assert single.case_count == 2


def test_from_records_unknown_type_raises():
    with pytest.raises(ValueError):
        from_records(query="q", expected_json_={}, tags_json_={"task_type": "typo"})


# ---- T902 100 基准 ----

_BENCHMARK = build_benchmark()


def test_benchmark_has_exactly_100_cases():
    assert _BENCHMARK.case_count == 100


def test_benchmark_five_types_equal_split():
    counts = dataset_spec_to_expected_count(_BENCHMARK)
    for task_type in (TASK_RETRIEVAL, TASK_NUMERIC, TASK_CITATION, TASK_ABSTENTION, TASK_PROVIDER):
        assert counts.get(task_type) == 20, task_type
    assert sum(counts.values()) == 100


def test_benchmark_abstention_mix():
    cases = [c for c in _BENCHMARK.cases if c.task_type == TASK_ABSTENTION]
    yes = sum(1 for c in cases if c.expected["expect_abstention"])
    no = len(cases) - yes
    assert yes == 12 and no == 8


# ---- T903–T907 评估器 ----


def test_retrieval_evaluator_recall():
    ev = get_evaluator(TASK_RETRIEVAL)
    case = CaseSpec("q", TASK_RETRIEVAL, expected={"expected_sources": ["a", "b"]})
    full = ev.evaluate(case, {"hits": ["a", "b", "c"]})
    assert full.passed and full.score == 1.0
    half = ev.evaluate(case, {"hits": ["a"]})
    assert not half.passed and half.score == 0.5


def test_numeric_evaluator_tolerance_and_unit():
    ev = get_evaluator(TASK_NUMERIC)
    case = CaseSpec(
        "q", TASK_NUMERIC, expected={"value": "0.1", "unit": "ratio", "tolerance": "0.001"}  # noqa: E501
    )
    ok = ev.evaluate(case, {"answer": 0.1004, "unit": "ratio"})
    assert ok.passed
    bad_unit = ev.evaluate(case, {"answer": 0.1004, "unit": "CNY"})
    assert not bad_unit.passed
    wrong = ev.evaluate(case, {"answer": 0.5})
    assert not wrong.passed


def test_numeric_evaluator_handles_decimal_answer():
    ev = get_evaluator(TASK_NUMERIC)
    case = CaseSpec("q", TASK_NUMERIC, expected={"value": "0.9174", "tolerance": "0.0005"})
    out = ev.evaluate(case, {"answer": Decimal("0.91745")})
    assert out.passed


def test_citation_evaluator_resolvability():
    ev = get_evaluator(TASK_CITATION)
    case = CaseSpec("q", TASK_CITATION, expected={"min_resolvable": 1, "expect_citation": True})
    ok = ev.evaluate(case, {"citations": ["src-1"], "valid_sources": ["src-1", "src-2"]})
    assert ok.passed
    unresolvable = ev.evaluate(case, {"citations": ["ghost"], "valid_sources": ["src-1"]})
    assert not unresolvable.passed
    no_citation = ev.evaluate(case, {"citations": [], "valid_sources": ["src-1"]})
    assert not no_citation.passed


def test_abstention_evaluator_consistency():
    ev = get_evaluator(TASK_ABSTENTION)
    should_abstain = CaseSpec("q", TASK_ABSTENTION, expected={"expect_abstention": True})
    assert ev.evaluate(should_abstain, {"abstained": True, "confidence_bucket": "ABSTAIN"}).passed
    assert not ev.evaluate(should_abstain, {"abstained": False}).passed
    should_answer = CaseSpec("q", TASK_ABSTENTION, expected={"expect_abstention": False})
    assert ev.evaluate(should_answer, {"abstained": False, "confidence_bucket": "HIGH"}).passed


def test_provider_reliability_evaluator():
    ev = get_evaluator(TASK_PROVIDER)
    strong = CaseSpec(
        "q", TASK_PROVIDER,
        expected={"expected_success_rate": 1.0, "min_successes": 1},  # noqa: E501
    )
    assert ev.evaluate(strong, {"attempts": 5, "successes": 5}).passed
    assert not ev.evaluate(strong, {"attempts": 5, "successes": 3}).passed
    degraded = CaseSpec(
        "q", TASK_PROVIDER,
        expected={"expected_success_rate": 0.8, "min_successes": 2},  # noqa: E501
    )
    ok = ev.evaluate(degraded, {"attempts": 5, "successes": 4})
    assert ok.passed and round(ok.score, 3) == 0.8


def test_unknown_evaluator_returns_none():
    assert get_evaluator("nope") is None


# ---- T908 decision（ADR-0015 决策级）----


def test_decision_evaluator_balanced_high_divergence():
    ev = get_evaluator(TASK_DECISION)
    case = CaseSpec("q", TASK_DECISION)
    assert ev.evaluate(case, {"disagreement": 0.6, "verdict": "balanced"}).passed


def test_decision_evaluator_rejects_confident_high_divergence():
    ev = get_evaluator(TASK_DECISION)
    case = CaseSpec("q", TASK_DECISION)
    # 高分歧却给出单边自信结论 -> 不一致。
    assert not ev.evaluate(case, {"disagreement": 0.6, "verdict": "bull"}).passed


def test_decision_evaluator_low_divergence_any_verdict():
    ev = get_evaluator(TASK_DECISION)
    case = CaseSpec("q", TASK_DECISION)
    assert ev.evaluate(case, {"disagreement": 0.2, "verdict": "bull"}).passed
    assert ev.evaluate(case, {"disagreement": 0.0, "verdict": "bear"}).passed


def test_decision_evaluator_missing_disagreement_fails():
    ev = get_evaluator(TASK_DECISION)
    case = CaseSpec("q", TASK_DECISION)
    assert not ev.evaluate(case, {"verdict": "balanced"}).passed


def test_decision_evaluator_out_of_range_fails():
    ev = get_evaluator(TASK_DECISION)
    case = CaseSpec("q", TASK_DECISION)
    assert not ev.evaluate(case, {"disagreement": 1.5, "verdict": "balanced"}).passed


# ---- T908 runner + 指标聚合 ----

# 一个满分替身 executor：按用例类型产出能通过的结果。


class PerfectExecutor:
    async def execute(self, case: CaseSpec):
        if case.task_type == TASK_RETRIEVAL:
            return {"hits": list(case.expected["expected_sources"])}
        if case.task_type == TASK_NUMERIC:
            return {"answer": case.expected["value"], "unit": case.expected.get("unit")}
        if case.task_type == TASK_CITATION:
            src = case.tags.get("query", "src-0")
            return {"citations": [src], "valid_sources": [src]}
        if case.task_type == TASK_ABSTENTION:
            return {"abstained": case.expected["expect_abstention"]}
        if case.task_type == TASK_PROVIDER:
            return {"attempts": 5, "successes": 5}
        return {}


@pytest.mark.asyncio
async def test_runner_aggregates_perfect_scores():
    runner = BenchmarkRunner(PerfectExecutor())
    report = await runner.run(_BENCHMARK)
    assert report.total == 100
    assert report.passed == 100
    assert report.pass_rate == 1.0
    assert report.avg_score == 1.0
    assert report.metrics["overall"]["total"] == 100
    assert len(report.metrics["per_type"]) == 5


@pytest.mark.asyncio
async def test_runner_persists_to_in_memory_store():
    store = InMemoryEvaluationStore()
    runner = BenchmarkRunner(PerfectExecutor(), store=store,
                             metadata=RunMetadata(git_commit="abc123", model_name="m"))
    report = await runner.run(_BENCHMARK)
    assert report.run_id
    assert len(store.datasets) == 1
    total_cases = sum(len(c) for c in store.cases.values())
    assert total_cases == 100
    assert len(store.runs) == 1
    run = store.runs[0]
    assert run["git_commit"] == "abc123"
    assert run["model_name"] == "m"
    assert run["metrics_json"]["overall"]["total"] == 100


@pytest.mark.asyncio
async def test_runner_store_none_overrides_constructor_store():
    store_in = InMemoryEvaluationStore()
    runner = BenchmarkRunner(PerfectExecutor(), store=store_in)
    spec = build_dataset(name="tiny", version="1",
                         cases=[CaseSpec("q", TASK_NUMERIC, expected={"value": "1.0"})])
    await runner.run(spec, store=None)
    assert not store_in.datasets  # 本次运行显式不落库


class FailingExecutor:
    """部分淘汰替身：retrieval 空召回、abstention 答反，其余按期望作答。"""

    async def execute(self, case: CaseSpec):
        if case.task_type == TASK_ABSTENTION:
            return {"abstained": not case.expected["expect_abstention"]}
        if case.task_type == TASK_RETRIEVAL:
            return {"hits": []}
        if case.task_type == TASK_NUMERIC:
            return {"answer": case.expected["value"], "unit": case.expected.get("unit")}
        if case.task_type == TASK_CITATION:
            src = case.tags.get("query", "src-0")
            return {"citations": [src], "valid_sources": [src]}
        if case.task_type == TASK_PROVIDER:
            return {"attempts": 5, "successes": 5}
        return {}


@pytest.mark.asyncio
async def test_runner_reflects_real_failures():
    runner = BenchmarkRunner(FailingExecutor())
    report = await runner.run(_BENCHMARK)
    assert 0 < report.pass_rate < 1.0
    assert report.metrics["overall"]["total"] == 100
    # 仅 retrieval + abstention 淘汰 → 通过恰好为 numeric/citation/provider 的 60 条。
    assert report.passed == 60


# ---- T909 可复现性元数据 ----


def test_metadata_fields_roundtrip():
    meta = collect_metadata(model_name="llama", embedding_model="bge-m3",
                            reranker_model="bge-reranker", config={"top_k": 10})
    assert meta.model_name == "llama"
    assert meta.embedding_model == "bge-m3"
    assert meta.reranker_model == "bge-reranker"
    assert meta.config == {"top_k": 10}


def test_git_commit_falls_back_in_non_git_dir(tmp_path: Path):
    meta = collect_metadata(cwd=str(tmp_path))
    assert meta.git_commit == "unknown"