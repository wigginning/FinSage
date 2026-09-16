"""评估域仓储：evaluation_datasets、evaluation_cases、evaluation_runs（规格 §5.19–5.21）。"""

from __future__ import annotations

from finsage.persistence.models.evaluation import EvaluationCase, EvaluationDataset, EvaluationRun
from finsage.persistence.repositories.base import FilteredRepository


class EvaluationDatasetRepository(FilteredRepository):
    """评价数据集仓储。白名单筛选：name / version / task_type。"""

    model = EvaluationDataset
    allow_filters = frozenset({"name", "version", "task_type"})

    def find_by_name_version(self, name: str, version: str):
        """按名称+版本取数据集（域对象或 None）。"""
        return self.find_one(name=name, version=version)


class EvaluationCaseRepository(FilteredRepository):
    """评估用例仓储。白名单筛选：dataset_id。"""

    model = EvaluationCase
    allow_filters = frozenset({"dataset_id"})

    def list_for_dataset(self, dataset_id: str, *, limit: int = 500, offset: int = 0) -> list:
        """按数据集取用例（域对象列表）。"""
        return self.find_many(dataset_id=dataset_id, limit=limit, offset=offset)


class EvaluationRunRepository(FilteredRepository):
    """评估运行仓储。白名单筛选：dataset_id / git_commit / model_name。"""

    model = EvaluationRun
    allow_filters = frozenset({"dataset_id", "git_commit", "model_name"})

    def list_for_dataset(self, dataset_id: str, *, limit: int = 200, offset: int = 0) -> list:
        """按数据集取评估运行（域对象列表）。"""
        return self.find_many(dataset_id=dataset_id, limit=limit, offset=offset)


__all__ = [
    "EvaluationDatasetRepository",
    "EvaluationCaseRepository",
    "EvaluationRunRepository",
]
