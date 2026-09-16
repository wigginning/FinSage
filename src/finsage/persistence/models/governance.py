"""治理/Provider 域模型：audit_events、provider_configs、provider_health。

对应规格 §5.16–5.18。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from finsage.persistence.base import Base, DateTime3, IdMixin, TimestampMixin, utcnow


class AuditEvent(IdMixin, Base):
    """审计事件（§5.16）。

    P2：审计保留策略 —— ``retention_days`` 提供清理窗口，由运维/后台任务按
    ``created_at < now - retention_days`` 批量删除，避免 audit_events 无限增长。
    """

    __tablename__ = "audit_events"
    __table_args__ = {"comment": "审计事件表"}

    tenant_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True, comment="租户ID（索引）"
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="链路 trace_id（索引）"
    )
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="请求 request_id（索引）"
    )
    stage: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="阶段（索引）"
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False, comment="行为主体：agent/node")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="模型名")
    tool: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="工具名")
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="Provider 名")
    input_json: Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="输入（JSON）")
    output_json: Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="输出（JSON）")
    latency_ms: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="耗时（毫秒）"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="状态：success/error/timeout"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误码")
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


def audit_retention_days() -> int:
    """审计事件默认保留天数（P2：防 audit_events 无限增长）。

    工程默认 90 天；运维可按需调低。清理逻辑由审计仓储提供
    ``purge_before(cutoff)``（见 repositories/governance.py）。
    """
    return 90


class ProviderConfig(IdMixin, TimestampMixin, Base):
    """Provider 配置（§5.17）。"""

    __tablename__ = "provider_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_name", name="uq_provider_configs_tenant_provider"),
        {"comment": "Provider 配置表"},
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引）",
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="Provider 名称")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否启用（TINYINT(1)）")
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="优先级（数值，越小越优先）"
    )
    config_json: Mapped[Any] = mapped_column(JSON, nullable=False, comment="自定义配置（JSON）")


class ProviderHealth(IdMixin, Base):
    """Provider 健康度（§5.18）。"""

    __tablename__ = "provider_health"
    __table_args__ = {"comment": "Provider 健康度表"}

    provider_name: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="Provider 名称（索引）"
    )
    capability: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="能力点（索引）"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="状态：healthy/degraded/down"
    )
    success_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, comment="成功率")
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="最近成功时间（UTC）"
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime3, nullable=True, comment="最近失败时间（UTC）"
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="累计失败次数"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, onupdate=utcnow, nullable=False, comment="更新时间（UTC）"
    )
