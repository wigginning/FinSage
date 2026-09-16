"""评估编排服务单测（ADR-0022）：数据集裁剪 + 缓冲重放 + 租户注入。

不依赖 DB / HTTP：直接驱动 ``evaluation_service``，用假 handle 记录事件、
用 ``InMemoryEvaluationStore`` 承接重放，验证 tenant_id 一路透传到落库调用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from finsage.api.evaluation_service import (
    EVALUATION_KIND,
    _BufferedStore,
    build_spec,
    run_evaluation,
)
from finsage.evaluation.dataset import TASK_NUMERIC, TASK_RETRIEVAL, CaseSpec
from finsage.evaluation.executors import DevEvalExecutor, build_dev_executor
from finsage.evaluation.runner import InMemoryEvaluationStore
from finsage.exceptions import FinSageError
from finsage.settings import Settings


@dataclass
class FakeHandle:
    """最小 TaskHandle 替身：只记录事件、进度与结果。"""

    task_id: str = "t-1"
    trace_id: str = "tr-1"
    progress: float = 0.0
    result: Any = None
    events: list[tuple[str, dict]] = field(default_factory=list)

    def emit(self, type_: str, data: dict | None = None) -> None:
        self.events.append((type_, data or {}))

    def set_progress(self, value: float) -> None:
        self.progress = value


@dataclass
class FakeDeps:
    settings: Settings = field(default_factory=lambda: Settings())
    evaluation_executor: Any = field(default_factory=build_dev_executor)


# ---- build_spec ----


def test_kind_constant():
    assert EVALUATION_KIND == "evaluation"


def test_build_spec_full_benchmark():
    spec = build_spec()
    assert spec.case_count == 100
    assert "subset" not in spec.name


def test_build_spec_filters_task_types():
    spec = build_spec(task_types=[TASK_NUMERIC])
    assert spec.case_count == 20
    assert {c.task_type for c in spec.cases} == {TASK_NUMERIC}
    assert spec.name.endswith("-subset")


def test_build_spec_limits_per_type():
    spec = build_spec(task_types=[TASK_NUMERIC, TASK_RETRIEVAL], limit_per_type=2)
    assert spec.case_count == 4
    counts: dict[str, int] = {}
    for case in spec.cases:
        counts[case.task_type] = counts.get(case.task_type, 0) + 1
    assert counts == {TASK_NUMERIC: 2, TASK_RETRIEVAL: 2}


def test_build_spec_is_deterministic():
    """同参数两次构建产出同序同内容（可复现性前提）。"""
    a = build_spec(task_types=[TASK_RETRIEVAL], limit_per_type=3)
    b = build_spec(task_types=[TASK_RETRIEVAL], limit_per_type=3)
    assert [c.query for c in a.cases] == [c.query for c in b.cases]


def test_build_spec_rejects_unknown_task_type():
    with pytest.raises(FinSageError) as exc:
        build_spec(task_types=["nope"])
    assert exc.value.code.value == "FIN-1001"


# ---- 缓冲重放 ----


async def test_buffered_store_replays_with_tenant():
    """缓冲的 persist_* 调用按原顺序重放，且 tenant_id 完整保留。"""
    deps = FakeDeps()
    spec = build_spec(task_types=[TASK_NUMERIC], limit_per_type=2)

    buffered = _BufferedStore()
    from finsage.evaluation.metadata import RunMetadata
    from finsage.evaluation.runner import BenchmarkRunner

    runner = BenchmarkRunner(deps.evaluation_executor, store=buffered, metadata=RunMetadata())
    report = await runner.run(spec, tenant_id="tenant-x")

    target = InMemoryEvaluationStore()
    buffered.replay(target)
    assert len(target.datasets) == 1
    dataset = next(iter(target.datasets.values()))
    assert dataset["tenant_id"] == "tenant-x"
    assert dataset["case_count"] == 2
    assert len(target.cases[dataset["id"]]) == 2
    assert len(target.runs) == 1
    assert target.runs[0]["tenant_id"] == "tenant-x"
    assert target.runs[0]["id"] == report.run_id
    assert target.runs[0]["metrics_json"] == report.metrics


# ---- run_evaluation ----


async def test_run_evaluation_populates_result():
    deps = FakeDeps()
    handle = FakeHandle()
    spec = build_spec(task_types=[TASK_NUMERIC], limit_per_type=3)

    await run_evaluation(deps, handle, spec=spec, tenant_id="tenant-a")

    assert handle.progress == pytest.approx(0.9)
    assert handle.result["case_count"] == 3
    assert handle.result["evaluated_count"] == 3
    assert handle.result["executor"] == "DevEvalExecutor"
    assert handle.result["persisted"] is False
    assert handle.result["metrics"]["overall"]["total"] == 3
    # 事件：开始 running + 结束 ok（复用 workflow.stage，不新增事件类型）。
    stages = [d for t, d in handle.events if t == "workflow.stage"]
    assert [s["status"] for s in stages] == ["running", "ok"]


async def test_run_evaluation_without_executor_raises():
    deps = FakeDeps(evaluation_executor=None)
    with pytest.raises(FinSageError) as exc:
        await run_evaluation(deps, FakeHandle(), spec=build_spec(limit_per_type=1))
    assert exc.value.code.value == "FIN-6001"


async def test_run_evaluation_persists_via_thread(monkeypatch):
    """persistence_enabled 时经 to_thread 重放落库（此处替身拦截，验证接线）。"""
    captured: dict[str, Any] = {}

    def fake_flush(buffered: _BufferedStore) -> None:
        target = InMemoryEvaluationStore()
        buffered.replay(target)
        captured["runs"] = target.runs

    monkeypatch.setattr("finsage.api.evaluation_service._flush_to_mysql", fake_flush)
    deps = FakeDeps(settings=Settings(enable_persistence=True))
    handle = FakeHandle()

    await run_evaluation(
        deps, handle, spec=build_spec(task_types=[TASK_NUMERIC], limit_per_type=1),
        tenant_id="tenant-b",
    )

    assert handle.result["persisted"] is True
    assert captured["runs"][0]["tenant_id"] == "tenant-b"


# ---- DevEvalExecutor 诚实性 ----


async def test_dev_executor_returns_none():
    """缺省执行器不伪造结果：返回 None，由 evaluator 据实评分。"""
    executor = DevEvalExecutor()
    result = await executor.execute(CaseSpec("q", TASK_NUMERIC, expected={"value": 1.0}))
    assert result is None
