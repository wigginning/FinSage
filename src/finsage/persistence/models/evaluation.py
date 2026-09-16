"""评估域模型：evaluation_datasets、evaluation_cases、evaluation_runs。

对应规格 §5.19–5.21。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from finsage.persistence.base import Base, DateTime3, IdMixin, utcnow


class EvaluationDataset(IdMixin, Base):
    """评估数据集（§5.19）。"""

    __tablename__ = "evaluation_datasets"
    __table_args__ = {"comment": "评估数据集表"}

    # ADR-0019 §5 + ADR-0022：评估域租户隔离。先加列 + 回填（0005），FinEval API
    # 落地（ADR-0022）后收紧为 NOT NULL（0006 迁移 + 本模型），强制按租户隔离。
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引；ADR-0022 强制隔离）",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="数据集名称")
    version: Mapped[str] = mapped_column(String(64), nullable=False, comment="数据集版本")
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="用例数量")
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class EvaluationCase(IdMixin, Base):
    """评估用例（§5.20）。"""

    __tablename__ = "evaluation_cases"
    __table_args__ = {"comment": "评估用例表"}

    # ADR-0019 §5 + ADR-0022：见 EvaluationDataset.tenant_id 说明（NOT NULL，强制隔离）。
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引；ADR-0022 强制隔离）",
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evaluation_datasets.id"),
        nullable=False,
        index=True,
        comment="所属数据集ID（外键，索引）",
    )
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="查询文本")
    expected_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="期望输出（JSON）")
    tags_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="标签（JSON）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class EvaluationRun(IdMixin, Base):
    """评估运行（§5.21）。"""

    __tablename__ = "evaluation_runs"
    __table_args__ = {"comment": "评估运行表"}

    # ADR-0019 §5 + ADR-0022：见 EvaluationDataset.tenant_id 说明（NOT NULL，强制隔离）。
    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引；ADR-0022 强制隔离）",
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_datasets.id"), nullable=False, comment="数据集ID（外键）"
    )
    git_commit: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="代码版本 git commit hash"
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="被评模型名")
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Embedding 模型"
    )
    reranker_model: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Reranker 模型"
    )
    config_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="运行配置（JSON）")
    metrics_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="评估指标（JSON）")
    started_at: Mapped[datetime] = mapped_column(
        DateTime3, nullable=False, comment="开始时间（UTC）"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="结束时间（UTC）"
    )
