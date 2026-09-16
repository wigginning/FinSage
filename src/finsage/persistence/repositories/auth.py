"""认证/租户域仓储：users、tenants、sessions（规格 §5.3–5.6）。

所有方法只返回 ORM 域对象，禁止跨层裸 dict（§4）。
"""

from __future__ import annotations

from sqlalchemy import select

from finsage.persistence.models.auth import Session, Tenant, User, UserTenant
from finsage.persistence.repositories.base import (
    BaseRepository,
    FilteredRepository,
    TenantScopedRepository,
)


class UserRepository(FilteredRepository):
    """用户仓储。白名单筛选：email / status。"""

    model = User
    allow_filters = frozenset({"email", "status"})

    def find_by_email(self, email: str):
        """按邮箱取用户（域对象或 None）。"""
        return self.find_one(email=email.lower() if email else email)


class TenantRepository(FilteredRepository):
    """租户仓储。白名单筛选：name / status。"""

    model = Tenant
    allow_filters = frozenset({"name", "status"})

    def find_by_name(self, name: str):
        """按租户名取租户（域对象或 None）。"""
        return self.find_one(name=name)


class SessionRepository(TenantScopedRepository):
    """会话仓储：注入租户后自动限该租户；白名单筛选：user_id / status。"""

    model = Session
    allow_filters = frozenset({"user_id", "status"})

    def list_for_user(self, user_id: str, *, limit: int = 100, offset: int = 0) -> list:
        """列出某用户的会话（域对象列表）。"""
        return self.find_many(user_id=user_id, limit=limit, offset=offset)


class UserTenantRepository(BaseRepository):
    """用户-租户关联仓储（复合主键表，仅提供按关联查询）。"""

    model = UserTenant
    allow_filters = frozenset({"user_id", "tenant_id"})

    def find(self, *, user_id: str | None = None, tenant_id: str | None = None) -> list:
        """按用户/租户联查归属关系（域对象列表）。"""
        stmt = select(UserTenant)
        if user_id is not None:
            stmt = stmt.where(UserTenant.user_id == user_id)
        if tenant_id is not None:
            stmt = stmt.where(UserTenant.tenant_id == tenant_id)
        return list(self._session.execute(stmt).scalars().all())
