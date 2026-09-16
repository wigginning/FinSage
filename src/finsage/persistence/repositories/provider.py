"""租户作用域仓储提供器（P0 —— TenantScopedRepository 接线）。

把既有但从未被请求路径消费的 ``TenantScopedRepository`` 接线到运行态：
``TenantRepositoryProvider`` 持有一个租户 id（来自请求身份），提供按需构造的
租户作用域仓储，使持久化端点的查询/写入自动附加 ``tenant_id`` 过滤（最小权限）。

用法（在启用持久化的请求处理中）：
    provider = TenantRepositoryProvider(tenant_id="t1")
    with provider.session() as session:
        docs = provider.document(session).list_by_ticker("300750")
        ...
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finsage.persistence.db import session_scope


@dataclass
class TenantRepositoryProvider:
    """按请求租户提供租户作用域仓储。

    ``tenant_id`` 为空表示不启用租户过滤（仅限系统级/无租户场景，勿用于多租户请求）。
    """

    tenant_id: str | None = None

    def session(self):
        """开启一个 DB 会话（commit/rollback/close 由上下文管理）。"""
        return session_scope()

    # ---- 各域租户作用域仓储（仅在调用时惰性构造，注入当前租户）----

    def document(self, session: Any):
        from finsage.persistence.repositories.rag import DocumentRepository

        return DocumentRepository(session, tenant_id=self.tenant_id)

    def evidence(self, session: Any):
        from finsage.persistence.repositories.research import EvidenceRepository

        return EvidenceRepository(session, tenant_id=self.tenant_id)

    def research_task(self, session: Any):
        from finsage.persistence.repositories.research import ResearchTaskRepository

        return ResearchTaskRepository(session, tenant_id=self.tenant_id)

    def session_repo(self, session: Any):
        from finsage.persistence.repositories.auth import SessionRepository

        return SessionRepository(session, tenant_id=self.tenant_id)

    def audit(self, session: Any):
        from finsage.persistence.repositories.governance import AuditEventRepository

        return AuditEventRepository(session, tenant_id=self.tenant_id)

    def provider_config(self, session: Any):
        from finsage.persistence.repositories.governance import ProviderConfigRepository

        return ProviderConfigRepository(session, tenant_id=self.tenant_id)


__all__ = ["TenantRepositoryProvider"]
