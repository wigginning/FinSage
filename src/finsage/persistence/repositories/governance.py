"""治理/Provider 域仓储：audit_events、provider_configs、provider_health（规格 §5.16–5.18）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from finsage.persistence.models.governance import (
    AuditEvent,
    ProviderConfig,
    ProviderHealth,
    audit_retention_days,
)
from finsage.persistence.repositories.base import FilteredRepository, TenantScopedRepository


class AuditEventRepository(TenantScopedRepository):
    """审计事件仓储：tenant_id 可空，注入租户后自动限该租户。

    白名单筛选：trace_id / request_id / stage / status。
    """

    model = AuditEvent
    allow_filters = frozenset({"trace_id", "request_id", "stage", "status"})

    def find_by_request_id(self, request_id: str):
        """按请求 id 取审计（域对象或 None）。"""
        return self.find_one(request_id=request_id)

    def purge_before(self, cutoff: datetime) -> int:
        """清理早于 cutoff 的审计事件（P2 保留策略），返回删除条数。"""
        stmt = delete(AuditEvent).where(AuditEvent.created_at < cutoff)
        # execute() 对 DML 返回 CursorResult（带 rowcount）；stub 把返回值定型为
        # 基类 Result，故显式 cast 到 CursorResult 以访问 rowcount。
        result = cast(CursorResult, self._session.execute(stmt))
        return int(result.rowcount or 0)

    def purge_older_than_days(self, days: int | None = None) -> int:
        """按保留天数清理过期审计（默认 90 天，见 audit_retention_days）。"""
        days = days if days is not None else audit_retention_days()
        cutoff = datetime.now() - timedelta(days=days)
        return self.purge_before(cutoff)


class ProviderConfigRepository(TenantScopedRepository):
    """Provider 配置仓储：注入租户后自动限该租户；白名单筛选：provider_name / enabled。"""

    model = ProviderConfig
    allow_filters = frozenset({"provider_name", "enabled"})

    def find_by_provider(self, provider_name: str):
        """按租户+Provider 名称取配置（域对象或 None）。"""
        return self.find_one(provider_name=provider_name)


class ProviderHealthRepository(FilteredRepository):
    """Provider 健康度仓储。白名单筛选：provider_name / capability / status。"""

    model = ProviderHealth
    allow_filters = frozenset({"provider_name", "capability", "status"})

    def find_health(self, provider_name: str, capability: str):
        """按 Provider+能力点取健康度（域对象或 None）。"""
        return self.find_one(provider_name=provider_name, capability=capability)

    def list_down(self, *, limit: int = 100, offset: int = 0) -> list:
        """列出异常（down/degraded）的 Provider 健康度（域对象列表）。"""
        stmt = select(ProviderHealth).where(ProviderHealth.status.in_(["down", "degraded"]))
        stmt = stmt.limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars().all())


__all__ = ["AuditEventRepository", "ProviderConfigRepository", "ProviderHealthRepository"]
