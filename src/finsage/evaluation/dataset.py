"""FinEval 数据集与用例格式（m09 T901，§5.19–5.20）。

框架级、确定性的数据契约：``CaseSpec`` / ``DatasetSpec`` 描述一条评估用例的
期望行为，并提供到 ``evaluation_cases`` 两列 JSON（``expected_json`` /
``tags_json``）与 ``evaluation_datasets`` 的序列化映射。规则：

- ``task_type`` 决定由哪个 evaluator（§m09 T903–T907）执行，取值固定五类；
- ``expected`` 为确定性的期望行为（禁止 LLM 生成 / 禁止编造）；
- 只做格式映射，不触及 DB 事务（DB 落库由 m01 EvaluationRepository 承担）。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# 评估任务与对应 evaluator（T903–T907 + ADR-0015 决策级）。前五类 FROZEN。
TASK_RETRIEVAL = "retrieval"
TASK_NUMERIC = "numeric"
TASK_CITATION = "citation"
TASK_ABSTENTION = "abstention"
TASK_PROVIDER = "provider_reliability"
TASK_DECISION = "decision"

TASK_TYPES: tuple[str, ...] = (
    TASK_RETRIEVAL,
    TASK_NUMERIC,
    TASK_CITATION,
    TASK_ABSTENTION,
    TASK_PROVIDER,
    TASK_DECISION,
)


@dataclass(frozen=True)
class CaseSpec:
    """一条评估用例（领域层）。"""

    query: str
    task_type: str
    # 该任务类型的确定性期望行为（evaluator 校验基准）。
    expected: dict[str, Any] = field(default_factory=dict)
    # 辅助元信息（分类/子主题等），进 tags_json。
    tags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task_type not in TASK_TYPES:
            raise ValueError(f"unsupported task_type: {self.task_type!r}")


@dataclass(frozen=True)
class DatasetSpec:
    """一个评估数据集（§5.19 字段 + 用例）。"""

    name: str
    version: str
    cases: tuple[CaseSpec, ...] = ()
    task_type: str = "combined"  # 单类型数据集可覆写

    @property
    def case_count(self) -> int:
        return len(self.cases)


def build_dataset(
    *,
    name: str,
    version: str,
    cases: Iterable[CaseSpec],
    task_type: str = "combined",
) -> DatasetSpec:
    """由用例序列构造数据集；task_type 为空则按单次任务自动填充。"""
    normalized = tuple(cases)
    types = {c.task_type for c in normalized}
    if task_type == "combined" and len(types) == 1:
        task_type = next(iter(types))
    return DatasetSpec(name=name, version=version, task_type=task_type, cases=normalized)


def expected_json(case: CaseSpec) -> dict[str, Any]:
    """evaluation_cases.expected_json —— 期望行为 JSON。"""
    return {"task_type": case.task_type, **case.expected}


def tags_json(case: CaseSpec) -> dict[str, Any]:
    """evaluation_cases.tags_json —— 已含 task_type 的标签 JSON。"""
    return {"task_type": case.task_type, **case.tags}


def from_records(
    *, query: str, expected_json_: dict[str, Any], tags_json_: dict[str, Any]
) -> CaseSpec:
    """由 DB 两列 JSON 还原领域用例（runner 从库回溯时用）。"""
    task_type = (tags_json_ or {}).get("task_type") or (expected_json_ or {}).get("task_type")
    if task_type not in TASK_TYPES:
        raise ValueError(f"cannot rebuild case: unknown task_type {task_type!r}")
    expected = dict(expected_json_ or {})
    expected.pop("task_type", None)
    tags = {k: v for k, v in (tags_json_ or {}).items() if k != "task_type"}
    return CaseSpec(query=query, task_type=task_type, expected=expected, tags=tags)


def dataset_spec_to_expected_count(spec: DatasetSpec) -> dict[str, int]:
    """按 task_type 统计用例数（用于校验 T902 的 100 条结构）。"""
    counts: dict[str, int] = {}
    for case in spec.cases:
        counts[case.task_type] = counts.get(case.task_type, 0) + 1
    return counts


__all__ = [
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
    "expected_json",
    "tags_json",
    "from_records",
    "dataset_spec_to_expected_count",
]