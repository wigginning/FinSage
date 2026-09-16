"""账号开通（ADR-0019 §4 的运营依赖）。

登录端点只做"凭据 → 令牌"，**不提供注册/开户**。本模块提供运维侧的账号开通能力：
创建（或重置）用户、确保其归属到指定租户并赋予角色，使账号可被 ``/auth/login`` 使用。

设计取舍：

- **不在 HTTP 层暴露开户端点**（即不做开放注册）：金融研究系统属内部/企业向，
  账号应由管理员开通；开放注册会把账号创建变成匿名可达的攻击面。
- **库函数 + CLI 薄壳**：核心逻辑在 ``provision_user``，接受外部 session，
  便于用内存 SQLite 做单测；``scripts/create_user.py`` 只负责参数解析与口令读取。
- **角色模型单一来源**：合法角色取自 ``api.auth.ROLE_RANK``，避免与 RBAC 判定漂移。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finsage.api.auth import ROLE_RANK  # ADR-0019 §1：角色模型的单一来源
from finsage.persistence.models.auth import Tenant, User, UserTenant
from finsage.persistence.repositories.auth import (
    TenantRepository,
    UserRepository,
    UserTenantRepository,
)
from finsage.security import hash_password

#: 合法角色（按等级升序，与 ROLE_RANK 一致）。
VALID_ROLES: tuple[str, ...] = tuple(sorted(ROLE_RANK, key=lambda r: ROLE_RANK[r]))

#: 默认最小口令长度（仅兜底弱口令，不做复杂度强制——由部署方口令策略决定）。
MIN_PASSWORD_LENGTH = 8


class ProvisionError(RuntimeError):
    """开通失败：角色非法、邮箱/口令不合规、用户已存在且未显式要求重置。"""


@dataclass(frozen=True)
class ProvisionResult:
    """开通结果（供 CLI 打印与测试断言）。"""

    user_id: str
    tenant_id: str
    tenant_name: str
    role: str
    created_user: bool
    created_tenant: bool
    created_membership: bool


def _ensure_tenant(session: Any, name: str) -> tuple[Tenant, bool]:
    """取或建租户，返回 ``(tenant, 是否新建)``。"""
    repo = TenantRepository(session)
    tenant = repo.find_by_name(name)
    if tenant is not None:
        return tenant, False
    tenant = Tenant(name=name, status="active")
    repo.add(tenant)
    session.flush()
    return tenant, True


def _ensure_user(
    session: Any,
    *,
    email: str,
    password: str,
    display_name: str,
    reset_password: bool,
) -> tuple[User, bool]:
    """取或建用户。**默认拒绝**改写既有账号，需显式 ``reset_password``。"""
    repo = UserRepository(session)
    user = repo.find_by_email(email)
    if user is None:
        created = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            status="active",
        )
        repo.add(created)
        session.flush()
        return created, True
    if not reset_password:
        raise ProvisionError(
            f"用户 {email} 已存在；如需重置口令请显式加 --reset-password（避免误改既有账号）"
        )
    user.password_hash = hash_password(password)
    # 重置口令时一并重新激活，否则"重置成功但仍登不进"会造成困惑。
    user.status = "active"
    session.flush()
    return user, False


def _ensure_membership(
    session: Any, *, user: User, tenant: Tenant, role: str
) -> tuple[str, bool]:
    """确保用户归属该租户且角色正确，返回 ``(role, 是否新建关联)``。"""
    repo = UserTenantRepository(session)
    rows = repo.find(user_id=user.id, tenant_id=tenant.id)
    if rows:
        rows[0].role = role  # 已存在则更新角色（改角色的常见运维操作）
        session.flush()
        return role, False
    repo.add(UserTenant(user_id=user.id, tenant_id=tenant.id, role=role))
    session.flush()
    return role, True


def provision_user(
    session: Any,
    *,
    email: str,
    password: str,
    tenant_name: str,
    role: str = "member",
    display_name: str | None = None,
    reset_password: bool = False,
    min_password_length: int = MIN_PASSWORD_LENGTH,
) -> ProvisionResult:
    """开通账号：确保用户存在、归属指定租户并具备角色。

    调用方负责事务提交/回滚（``session_scope`` 或测试 session）。
    仅做校验与写入；失败抛 ``ProvisionError``。
    """
    if role not in ROLE_RANK:
        raise ProvisionError(f"非法角色 {role!r}；可选：{', '.join(VALID_ROLES)}")
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized:
        raise ProvisionError(f"邮箱格式不合法：{email!r}")
    if len(password or "") < min_password_length:
        raise ProvisionError(f"口令至少 {min_password_length} 位")
    if not (tenant_name or "").strip():
        raise ProvisionError("租户名不能为空")

    tenant, created_tenant = _ensure_tenant(session, tenant_name.strip())
    user, created_user = _ensure_user(
        session,
        email=normalized,
        password=password,
        display_name=display_name or normalized.split("@", 1)[0],
        reset_password=reset_password,
    )
    final_role, created_membership = _ensure_membership(
        session, user=user, tenant=tenant, role=role
    )
    return ProvisionResult(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=final_role,
        created_user=created_user,
        created_tenant=created_tenant,
        created_membership=created_membership,
    )


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "ProvisionError",
    "ProvisionResult",
    "VALID_ROLES",
    "provision_user",
]
