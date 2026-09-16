"""FinEval 评估框架（m09，§5.19–5.21 / §31.10）。

对外入口：
- 数据集/用例格式        : ``CaseSpec`` / ``DatasetSpec`` / ``build_dataset``
- 五类评估器            : ``get_evaluator`` / ``available_evaluators``
- 100 基准用例          : ``build_benchmark``
- benchmark runner     : ``BenchmarkRunner``（可落 evaluation_* 表）
- 可复现性元数据         : ``collect_metadata`` / ``RunMetadata``

纪律：指标仅由实际 outcomes 计算，禁止编造 benchmark（AGENTS.md §10/§31.10）。
"""
from __future__ import annotations

from .benchmarks import build_benchmark
from .dataset import (
    TASK_ABSTENTION,
    TASK_CITATION,
    TASK_DECISION,
    TASK_NUMERIC,
    TASK_PROVIDER,
    TASK_RETRIEVAL,
    TASK_TYPES,
    CaseSpec,
    DatasetSpec,
    build_dataset,
)
from .evaluators import (
    EvalOutcome,
    Evaluator,
    available_evaluators,
    get_evaluator,
)
from .metadata import RunMetadata, collect_metadata
from .runner import (
    BenchmarkReport,
    BenchmarkRunner,
    CaseExecutor,
    EvaluationStore,
    InMemoryEvaluationStore,
    SQLAlchemyEvaluationStore,
)

__all__ = [
    "build_benchmark",
    "TASK_TYPES",
    "TASK_RETRIEVAL",
    "TASK_NUMERIC",
    "TASK_CITATION",
    "TASK_ABSTENTION",
    "TASK_PROVIDER",
    "TASK_DECISION",
    "CaseSpec",
    "DatasetSpec",
    "build_dataset",
    "EvalOutcome",
    "Evaluator",
    "available_evaluators",
    "get_evaluator",
    "RunMetadata",
    "collect_metadata",
    "BenchmarkReport",
    "BenchmarkRunner",
    "CaseExecutor",
    "EvaluationStore",
    "InMemoryEvaluationStore",
    "SQLAlchemyEvaluationStore",
]