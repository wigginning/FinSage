"""登录认证服务（ADR-0019 §4）。

把"凭据 → 身份令牌"的**发行**闭环起来（此前只有 ``sign_token`` 辅助函数，没有任何
调用方，导致身份令牌无人可签发）。流程：

1. 按 email 取用户；不存在时对 ``DUMMY_HASH`` 做一次同等开销的校验（时序对齐）；
2. ``verify_password`` 恒定时间校验口令；
3. 取该用户在租户内的角色（``user_tenants.role`` —— ADR-0019 §2 的**签发源**）；
4. 用 ``identity_token.sign_token`` 签发令牌（``user_id``/``tenant_id``/``roles=[role]``/``exp``），
   令牌即运行时的**权威**（``resolve_principal`` 侧验签后不再回查 DB）。

安全约束：

- 失败一律返回 ``None``，**不区分**"账号不存在 / 口令错误 / 账号未激活 / 无租户归属 /
  指定租户不属于该用户"，由路由层统一转成 FIN-1002，避免账号枚举。
- 核心逻辑 ``authenticate`` 接受外部 session，便于用内存 SQLite 做单测（对齐
  ``tests/unit/test_repository.py`` 的做法）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finsage.api.identity_token import sign_token
from finsage.persistence.db import session_scope
from finsage.persistence.repositories.auth import UserRepository, UserTenantRepository
from finsage.security import DUMMY_HASH, verify_password
from finsage.settings import Settings, get_settings

# users.status 的激活值（§5.3）；其余一律视为不可登录。
_ACTIVE = "active"


@dataclass(frozen=True)
class AuthContext:
    """登录成功后的身份上下文（租户内角色即令牌 roles 的来源）。"""

    user_id: str
    tenant_id: str
    role: str


def _pick_membership(memberships: list[Any], tenant_id: str | None) -> Any | None:
    """选定租户归属：显式指定优先；未指定取最早的一条（保证选择稳定可预期）。"""
    if tenant_id:
        return next((m for m in memberships if m.tenant_id == tenant_id), None)
    ordered = sorted(memberships, key=lambda m: (str(m.created_at), str(m.tenant_id)))
    return ordered[0] if ordered else None


def authenticate(
    session: Any,
    *,
    email: str,
    password: str,
    tenant_id: str | None = None,
) -> AuthContext | None:
    """在给定 session 上完成凭据校验与租户/角色解析；失败返回 None（不区分原因）。"""
    user = UserRepository(session).find_by_email(email)
    # 时序对齐：账号不存在/无口令哈希时，仍对诱饵哈希执行一次同等开销的派生。
    encoded = user.password_hash if (user is not None and user.password_hash) else DUMMY_HASH
    password_ok = verify_password(password, encoded)

    if user is None or not user.password_hash:
        return None
    if user.status != _ACTIVE:
        return None
    if not password_ok:
        return None

    memberships = UserTenantRepository(session).find(user_id=user.id)
    if not memberships:
        return None
    chosen = _pick_membership(memberships, tenant_id)
    if chosen is None:
        return None
    return AuthContext(user_id=user.id, tenant_id=chosen.tenant_id, role=chosen.role)


class AuthService:
    """登录服务：签发身份令牌。

    未注入 session 时自行开 ``session_scope``；测试可直接注入内存 SQLite session。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def login(
        self,
        *,
        email: str,
        password: str,
        tenant_id: str | None = None,
        session: Any = None,
    ) -> tuple[AuthContext, str, int] | None:
        """成功返回 ``(AuthContext, token, expires_in)``；失败返回 ``None``。

        ``identity_token_secret`` 未配置时返回 ``None`` —— 没有密钥就无法签发，
        诚实失败而不是降级成"无身份放行"（由路由层转成错误响应）。
        """
        if session is not None:
            ctx = authenticate(session, email=email, password=password, tenant_id=tenant_id)
        else:
            with session_scope() as s:
                ctx = authenticate(s, email=email, password=password, tenant_id=tenant_id)
        if ctx is None or not self._settings.identity_token_secret:
            return None

        ttl = int(self._settings.identity_token_ttl)
        token = sign_token(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            secret=self._settings.identity_token_secret,
            roles=[ctx.role],
            ttl_seconds=ttl,
        )
        return ctx, token, ttl


__all__ = ["AuthContext", "AuthService", "authenticate"]
