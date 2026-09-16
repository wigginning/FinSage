"""研究域模型：research_tasks、research_runs。

对应规格 §5.14–5.15。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from finsage.persistence.base import Base, DateTime3, IdMixin, utcnow


class ResearchTask(IdMixin, Base):
    """研究任务（§5.14）。"""

    __tablename__ = "research_tasks"
    __table_args__ = {"comment": "研究任务表"}

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引）",
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
        comment="会话ID（外键，索引）",
    )
    type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="任务类型：research_qa/financial_health/due_diligence/report/api/upload",
    )
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="用户查询文本")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="任务状态：pending/running/succeeded/failed/cancelled"
    )
    trace_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="链路 trace_id（唯一）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="开始时间（UTC）"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="结束时间（UTC）"
    )


class ResearchRun(IdMixin, Base):
    """研究运行记录（§5.15）。"""

    __tablename__ = "research_runs"
    __table_args__ = {"comment": "研究运行记录表"}

    research_task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("research_tasks.id"),
        nullable=False,
        index=True,
        comment="研究任务ID（外键，索引）",
    )
    workflow_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="工作流名称")
    graph_version: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="LangGraph 图版本"
    )
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="主模型名称")
    model_version: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="主模型版本"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="运行状态：running/succeeded/failed"
    )
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6), nullable=True, comment="整体置信度"
    )
    result_json: Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="运行结果（JSON）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="结束时间（UTC）"
    )
