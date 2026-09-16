"""FinEval benchmark runner（m09 T908，§5.21 evaluation_runs）。

- ``CaseExecutor``：可注入的任务执行器（生产包装 m06 图；测试注入替身）；
- ``EvaluationStore``：可选落库（``InMemoryEvaluationStore`` 内置；
  ``SQLAlchemyEvaluationStore`` 用 m01 EvaluationRepository 落 evaluation_* 表）；
- 指标聚合：overall + 按 task_type 汇总，**仅由实际 outcomes 计算，禁止编造**
  （AGENTS.md §10/§31.10）；报告经 ``report_to_metrics`` 序列化为可落库 JSON。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from finsage.observability.trace import uuid_str

from .dataset import CaseSpec, DatasetSpec
from .evaluators import EvalOutcome, get_evaluator
from .metadata import RunMetadata

# ---- 契约 ----


class CaseExecutor(Protocol):
    """执行一条用例并返回该 task_type 的确定性 result（契约见 evaluators）。"""

    async def execute(self, case: CaseSpec) -> Any: ...


class EvaluationStore(Protocol):
    """可选落库组件（写入 evaluation_* 表）。

    ``tenant_id`` 由调用方（FinEval API，ADR-0022）注入，用于按租户强制隔离——
    评估运行归属到发起租户，读取时按租户过滤。
    """

    def persist_dataset(
        self, spec: DatasetSpec, dataset_id: str, *, tenant_id: str = ""
    ) -> None: ...
    def persist_cases(self, spec: DatasetSpec, dataset_id: str) -> int: ...
    def persist_run(
        self,
        *,
        run_id: str,
        dataset_id: str,
        metadata: RunMetadata,
        metrics: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        tenant_id: str = "",
    ) -> None: ...


# ---- 指标聚合 ----


@dataclass
class TypeMetrics:
    task_type: str
    total: int = 0
    passed: int = 0
    score_sum: float = 0.0

    @property
    def pass_rate(self) -> float:
        return 0.0 if self.total == 0 else round(self.passed / self.total, 4)

    @property
    def avg_score(self) -> float:
        return 0.0 if self.total == 0 else round(self.score_sum / self.total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "total": self.total,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "avg_score": self.avg_score,
        }


@dataclass
class BenchmarkReport:
    dataset_name: str
    dataset_version: str
    run_id: str | None
    git_commit: str
    started_at: datetime
    finished_at: datetime
    outcomes: list[EvalOutcome] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def pass_rate(self) -> float:
        return 0.0 if self.total == 0 else round(self.passed / self.total, 4)

    @property
    def avg_score(self) -> float:
        if self.total == 0:
            return 0.0
        return round(sum(o.score for o in self.outcomes) / self.total, 4)


def report_to_metrics(report: BenchmarkReport) -> dict[str, Any]:
    """把报告聚合为可落 evaluation_runs.metrics_json 的结构化指标。"""
    by_type: dict[str, TypeMetrics] = {}
    for outcome in report.outcomes:
        bucket = by_type.setdefault(outcome.task_type, TypeMetrics(outcome.task_type))
        bucket.total += 1
        bucket.score_sum += outcome.score
        bucket.passed += 1 if outcome.passed else 0
    return {
        "overall": {
            "total": report.total,
            "passed": report.passed,
            "pass_rate": report.pass_rate,
            "avg_score": report.avg_score,
        },
        "per_type": {k: v.to_dict() for k, v in sorted(by_type.items())},
    }


# ---- 内置内存 store ----


@dataclass
class InMemoryEvaluationStore:
    """进程内落库替身；内存即可读回，供无 DB 环境 / 测试使用。"""

    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    cases: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)

    def persist_dataset(self, spec: DatasetSpec, dataset_id: str, *, tenant_id: str = "") -> None:
        self.datasets[dataset_id] = {
            "id": dataset_id,
            "name": spec.name,
            "version": spec.version,
            "task_type": spec.task_type,
            "case_count": spec.case_count,
            "tenant_id": tenant_id,
        }

    def persist_cases(self, spec: DatasetSpec, dataset_id: str) -> int:
        from .dataset import expected_json, tags_json

        records = [
            {"dataset_id": dataset_id, "query": c.query, "expected_json": expected_json(c),
             "tags_json": tags_json(c)}
            for c in spec.cases
        ]
        self.cases[dataset_id] = records
        return len(records)

    def persist_run(
        self,
        *,
        run_id: str,
        dataset_id: str,
        metadata: RunMetadata,
        metrics: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        tenant_id: str = "",
    ) -> None:
        self.runs.append(
            {
                "id": run_id,
                "dataset_id": dataset_id,
                "tenant_id": tenant_id,
                "git_commit": metadata.git_commit,
                "model_name": metadata.model_name,
                "embedding_model": metadata.embedding_model,
                "reranker_model": metadata.reranker_model,
                "config_json": metadata.config,
                "metrics_json": metrics,
                "started_at": started_at,
                "finished_at": finished_at,
            }
        )


# ---- SQL store（m01 EvaluationRepository 适配）----


class SQLAlchemyEvaluationStore:
    """将 benchmark 结果写入 evaluation_* 表（§5.19–5.21，T908 落库）。

    事务纪律：dataset/cases 仅 ``add`` 到会话；``persist_run`` 时把 run 一并
    ``commit``（事务终点统一提交，避免部分失败时不一致）。依赖调用方提供
    SQLAlchemy Session。
    """

    def __init__(self, session) -> None:
        from finsage.persistence.repositories.evaluation import (
            EvaluationCaseRepository,
            EvaluationDatasetRepository,
            EvaluationRunRepository,
        )

        self.datasets = EvaluationDatasetRepository(session)
        self.cases_repo = EvaluationCaseRepository(session)
        self.runs = EvaluationRunRepository(session)
        self._tenant_id: str = ""

    def persist_dataset(self, spec: DatasetSpec, dataset_id: str, *, tenant_id: str = "") -> None:
        from finsage.persistence.models.evaluation import EvaluationDataset

        # 供 persist_cases 复用的租户归属（run() 先调 persist_dataset 再调 persist_cases）。
        self._tenant_id = tenant_id
        self.datasets.add(
            EvaluationDataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name=spec.name,
                version=spec.version,
                task_type=spec.task_type,
                case_count=spec.case_count,
            )
        )

    def persist_cases(self, spec: DatasetSpec, dataset_id: str) -> int:
        from finsage.persistence.models.evaluation import EvaluationCase

        from .dataset import expected_json, tags_json

        for case in spec.cases:
            self.cases_repo.add(
                EvaluationCase(
                    dataset_id=dataset_id,
                    tenant_id=self._tenant_id,
                    query=case.query,
                    expected_json=expected_json(case),
                    tags_json=tags_json(case),
                )
            )
        return spec.case_count

    def persist_run(
        self,
        *,
        run_id: str,
        dataset_id: str,
        metadata: RunMetadata,
        metrics: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        tenant_id: str = "",
    ) -> None:
        from finsage.persistence.models.evaluation import EvaluationRun

        self.runs.add(
            EvaluationRun(
                id=run_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                git_commit=metadata.git_commit,
                model_name=metadata.model_name,
                embedding_model=metadata.embedding_model,
                reranker_model=metadata.reranker_model,
                config_json=metadata.config,
                metrics_json=metrics,
                started_at=started_at,
                finished_at=finished_at,
            )
        )
        self.runs._session.commit()  # noqa: SLF001 —— 事务终点统一提交


# ---- runner ----

# run() 的 store 哨兵：仅当调用方未显式传参（等于此哨兵）才回落构造时 store；
# 显式传 None 表示本次不落库。标注 Any 才能作为 `EvaluationStore | None` 形参的缺省值。
_NO_STORE: Any = object()


class BenchmarkRunner:
    """执行一个数据集并聚合可复现指标。持久化经 ``store``（缺省不落库）。"""

    def __init__(
        self,
        executor: CaseExecutor,
        *,
        store: EvaluationStore | None = None,
        metadata: RunMetadata | None = None,
    ) -> None:
        self._executor = executor
        self._store = store
        self._metadata = metadata or RunMetadata()

    async def run(
        self,
        spec: DatasetSpec,
        *,
        metadata: RunMetadata | None = None,
        store: EvaluationStore | None = _NO_STORE,
        tenant_id: str = "",
    ) -> BenchmarkReport:
        """执行 ``spec`` 全部用例。``metadata``/``store`` 可在单次运行覆写默认值。

        ``store`` 缺省用构造时 store；显式传 ``None`` 表示本次不落库（覆写构造默认）。
        ``tenant_id`` 注入落库组件，用于按租户隔离（ADR-0022）。
        """
        run_meta = metadata or self._metadata
        # 哨兵判断：未显式传参 → 回落构造时 store；显式 None → 不落库。
        active_store = self._store if store is _NO_STORE else store
        started = datetime.now(UTC)
        outcomes: list[EvalOutcome] = []
        for case in spec.cases:
            evaluator = get_evaluator(case.task_type)
            if evaluator is None:  # 未知 task_type：跳过且不计数（No-Guess）
                continue
            result = await self._executor.execute(case)
            outcomes.append(evaluator.evaluate(case, result))
        finished = datetime.now(UTC)
        report = BenchmarkReport(
            dataset_name=spec.name,
            dataset_version=spec.version,
            run_id=None,
            git_commit=run_meta.git_commit,
            started_at=started,
            finished_at=finished,
            outcomes=outcomes,
        )
        report.metrics = report_to_metrics(report)
        if active_store is not None:
            dataset_id = uuid_str()
            active_store.persist_dataset(spec, dataset_id, tenant_id=tenant_id)
            active_store.persist_cases(spec, dataset_id)
            report.run_id = uuid_str()
            active_store.persist_run(
                run_id=report.run_id,
                dataset_id=dataset_id,
                metadata=run_meta,
                metrics=report.metrics,
                started_at=started,
                finished_at=finished,
                tenant_id=tenant_id,
            )
        return report


__all__ = [
    "CaseExecutor",
    "EvaluationStore",
    "BenchmarkReport",
    "TypeMetrics",
    "report_to_metrics",
    "InMemoryEvaluationStore",
    "SQLAlchemyEvaluationStore",
    "BenchmarkRunner",
]