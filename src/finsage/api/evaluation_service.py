"""评估运行编排服务（ADR-0022）。

职责：把一次 FinEval benchmark 运行封装为可被 ``TaskManager`` 调度的后台作业——
构建数据集 spec → 跑 ``BenchmarkRunner`` → 落库（按全局持久化开关）→ 产出 §26.9 事件。

**缓冲后重放**（ADR-0022 §4）：``EvaluationStore`` 协议是同步的，若在 async ``run()``
内直连 MySQL 会阻塞事件循环（违反仓库「同步 DB I/O 一律 ``to_thread``」约定）。
故运行期用 ``_BufferedStore`` 收集 ``persist_*`` 调用（零 I/O），运行结束后在
``asyncio.to_thread`` 中于单个 ``session_scope()`` 内重放提交。

诚实纪律：指标只由 evaluator 对**实际** executor 输出评分产生；缺省 ``DevEvalExecutor``
返回 ``None``，评分据实偏低，**不伪装**真实评测能力（AGENTS.md §10/§31.10）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from finsage.evaluation.benchmarks import build_benchmark
from finsage.evaluation.dataset import TASK_TYPES, DatasetSpec, build_dataset
from finsage.evaluation.metadata import RunMetadata, collect_metadata
from finsage.evaluation.runner import BenchmarkRunner
from finsage.exceptions import ErrorCode, raise_for_code

# 评估任务 kind（TaskManager 列表/筛选用；与 chat/research 并列）。
EVALUATION_KIND = "evaluation"

# §26.9 事件：评估阶段推进（复用 workflow.stage，不新增事件类型）。
_STAGE_EVENT = "workflow.stage"


# ---- 数据集构建 ----


def build_spec(
    *,
    task_types: list[str] | None = None,
    limit_per_type: int | None = None,
) -> DatasetSpec:
    """由 100 条基准派生本次运行的数据集。

    - ``task_types``：只保留指定任务类型（``None`` 表示全部）；非法取值抛 ``FIN-1001``；
    - ``limit_per_type``：每类型最多取前 N 条（冒烟用，保持基准内条目顺序确定性）。

    过滤后为空即抛 ``FIN-1001``——空数据集跑出的 0 分是无意义指标，不允许提交。
    """
    base = build_benchmark()
    selected = list(task_types) if task_types else []
    unknown = [t for t in selected if t not in TASK_TYPES]
    if unknown:
        raise_for_code(ErrorCode.INVALID_REQUEST, f"unsupported task_type: {unknown!r}")

    wanted = set(selected) if selected else None
    counters: dict[str, int] = {}
    cases = []
    for case in base.cases:
        if wanted is not None and case.task_type not in wanted:
            continue
        if limit_per_type is not None:
            used = counters.get(case.task_type, 0)
            if used >= limit_per_type:
                continue
            counters[case.task_type] = used + 1
        cases.append(case)

    if not cases:
        raise_for_code(ErrorCode.INVALID_REQUEST, "dataset selection produced zero cases")

    # 派生集用 base 的 name/version 加后缀，避免与完整基准运行混淆。
    suffix = "" if wanted is None and limit_per_type is None else "-subset"
    return build_dataset(
        name=f"{base.name}{suffix}",
        version=base.version,
        cases=cases,
    )


# ---- 缓冲 store（运行期零 I/O，结束后重放）----


@dataclass
class _DatasetCall:
    spec: DatasetSpec
    dataset_id: str
    tenant_id: str


@dataclass
class _RunCall:
    run_id: str
    dataset_id: str
    metadata: RunMetadata
    metrics: dict[str, Any]
    started_at: datetime
    finished_at: datetime
    tenant_id: str


@dataclass
class _BufferedStore:
    """记录 ``persist_*`` 调用，供运行结束后在线程池内重放到真实 store。"""

    dataset_call: _DatasetCall | None = None
    cases_calls: list[tuple[DatasetSpec, str]] = field(default_factory=list)
    run_call: _RunCall | None = None

    def persist_dataset(self, spec: DatasetSpec, dataset_id: str, *, tenant_id: str = "") -> None:
        self.dataset_call = _DatasetCall(spec=spec, dataset_id=dataset_id, tenant_id=tenant_id)

    def persist_cases(self, spec: DatasetSpec, dataset_id: str) -> int:
        self.cases_calls.append((spec, dataset_id))
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
        self.run_call = _RunCall(
            run_id=run_id,
            dataset_id=dataset_id,
            metadata=metadata,
            metrics=metrics,
            started_at=started_at,
            finished_at=finished_at,
            tenant_id=tenant_id,
        )

    def replay(self, target: Any) -> None:
        """把缓冲的调用按原顺序重放到目标 store（同步，须在线程池内调用）。"""
        if self.dataset_call is not None:
            call = self.dataset_call
            target.persist_dataset(call.spec, call.dataset_id, tenant_id=call.tenant_id)
        for spec, dataset_id in self.cases_calls:
            target.persist_cases(spec, dataset_id)
        if self.run_call is not None:
            r = self.run_call
            target.persist_run(
                run_id=r.run_id,
                dataset_id=r.dataset_id,
                metadata=r.metadata,
                metrics=r.metrics,
                started_at=r.started_at,
                finished_at=r.finished_at,
                tenant_id=r.tenant_id,
            )


def _flush_to_mysql(buffered: _BufferedStore) -> None:
    """在单个会话内重放缓冲写入（同步，供 ``to_thread`` 调用）。"""
    from finsage.evaluation.runner import SQLAlchemyEvaluationStore
    from finsage.persistence.db import session_scope

    with session_scope() as session:
        buffered.replay(SQLAlchemyEvaluationStore(session))


# ---- 运行编排 ----


async def run_evaluation(
    deps: Any,
    handle: Any,
    *,
    spec: DatasetSpec,
    tenant_id: str = "",
) -> None:
    """执行一次 benchmark 并把结果写入 ``handle.result``（供状态端点读取）。

    由 ``TaskManager`` 调度：本函数只负责领域推进与事件产出，状态机
    （running/completed/failed）由 manager 接管。
    """
    executor = getattr(deps, "evaluation_executor", None)
    if executor is None:
        # 无执行器则无法产生任何真实指标 —— 诚实失败，不返回编造的 0 分报告。
        raise_for_code(ErrorCode.INTERNAL_ERROR, "evaluation executor not configured")

    settings = getattr(deps, "settings", None)
    persist = bool(getattr(settings, "persistence_enabled", False))
    buffered = _BufferedStore()
    metadata = collect_metadata(
        model_name=getattr(settings, "llm_model", "") or "",
        config={"persistence": persist, "executor": type(executor).__name__},
    )

    handle.emit(
        _STAGE_EVENT,
        {
            "name": "evaluation",
            "status": "running",
            "dataset": spec.name,
            "case_count": spec.case_count,
        },
    )
    runner = BenchmarkRunner(executor, store=buffered, metadata=metadata)
    report = await runner.run(spec, tenant_id=tenant_id)
    handle.set_progress(0.9)

    persisted = False
    if persist:
        # 同步 DB I/O 移出事件循环；失败不吞：由 manager 折成 task.failed（可诊断）。
        await asyncio.to_thread(_flush_to_mysql, buffered)
        persisted = True

    handle.emit(
        _STAGE_EVENT,
        {"name": "evaluation", "status": "ok", "persisted": persisted},
    )
    handle.result = {
        "run_id": report.run_id,
        "dataset_name": report.dataset_name,
        "dataset_version": report.dataset_version,
        "case_count": spec.case_count,
        "evaluated_count": report.total,
        "git_commit": report.git_commit,
        "executor": type(executor).__name__,
        "persisted": persisted,
        "metrics": report.metrics,
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat(),
    }


__all__ = ["EVALUATION_KIND", "build_spec", "run_evaluation"]
