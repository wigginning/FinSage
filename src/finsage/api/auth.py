"""API 鉴权中间件（m08，T801，§7/§8）。

Bearer token 鉴权：
- 从 ``Authorization: Bearer <token>`` 提取令牌；
- 与 ``settings.api_token`` 比对：配置为空 = 开发环境关闭鉴权（放行）；
  配置非空但缺失 → FIN-1002 AUTH_REQUIRED(401)，不匹配 → FIN-1003 FORBIDDEN(403)。
- 在静态 token 之上，若令牌为签名身份令牌（``api.identity_token``，密钥
  ``settings.identity_token_secret``），则解析出 ``Principal``（user_id / tenant_id / roles），
  供接口做资源级最小权限校验（P0 权限数据面）。

角色校验（ADR-0019）：``require_role(minimum)`` 在已验签身份令牌的 ``roles`` 之上做
RBAC 判定（viewer < member < admin < owner）。令牌为运行时权威，签发源是 DB
``user_tenants.role``；静态 token / 匿名请求无 roles，按 member 级处理。

对外仍只暴露 FIN 错误码与稳定 message，不泄露内部异常文本（§8）。
"""
from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from finsage.api.context import ANONYMOUS, Principal
from finsage.api.identity_token import parse_principal_payload, verify_token
from finsage.exceptions import ErrorCode, raise_for_code
from finsage.settings import Settings, get_settings

_security = HTTPBearer(auto_error=False)


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    """取 Bearer 令牌；缺失返回空串。"""
    return credentials.credentials if credentials is not None else ""


def _settings(request: Request) -> Settings:
    """优先取 app.state.settings（供测试/子应用注入），否则回退全局配置。"""
    return getattr(request.app.state, "settings", None) or get_settings()


def _is_valid_identity_token(token: str, settings: Settings) -> bool:
    """是否携带可校验的身份令牌（配置了 identity secret 时）。"""
    if not settings.identity_token_secret:
        return False
    return verify_token(token, secret=settings.identity_token_secret) is not None


def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),  # noqa: B008
) -> None:
    """路由级鉴权依赖：校验 Bearer token 是否匹配配置。

    接受两种凭证：静态 ``api_token``（既有）或有效签名身份令牌（P0 认证升级）。
    配置为空 = 开发环境关闭鉴权（放行）。
    """
    settings = _settings(request)
    if not settings.api_token and not settings.identity_token_secret:
        return  # 开发环境未配置令牌，关闭鉴权
    provided = _bearer_token(credentials)
    if not provided:
        raise_for_code(ErrorCode.AUTH_REQUIRED, "missing bearer token")
    if settings.api_token and secrets.compare_digest(provided, settings.api_token):
        return
    if _is_valid_identity_token(provided, settings):
        return
    raise_for_code(ErrorCode.FORBIDDEN, "invalid bearer token")


def _bearer_token_from_header(request: Request) -> str:
    """直接从请求头提取 Bearer 令牌（供非依赖路径复用）。"""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def resolve_principal(request: Request) -> Principal:
    """从请求 Bearer 令牌解析身份；无有效身份令牌返回匿名 Principal。

    - 令牌为签名身份令牌 → 解析 user_id / tenant_id 构造 Principal；
    - 否则返回 ``ANONYMOUS``（无租户作用域，配合静态 api_token 的开发放行）。
    """
    settings = _settings(request)
    token = _bearer_token_from_header(request)
    if not token or not settings.identity_token_secret:
        return ANONYMOUS
    payload: Any = verify_token(token, secret=settings.identity_token_secret)
    if payload is None:
        return ANONYMOUS
    fields = parse_principal_payload(payload)
    roles = payload.get("roles") or []
    return Principal(
        user_id=fields["user_id"],
        tenant_id=fields["tenant_id"],
        roles=frozenset(roles) if isinstance(roles, list) else frozenset(),
    )


def require_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),  # noqa: B008
) -> Principal:
    """路由级依赖：先鉴权，再解析并返回 Principal。

    在 ``require_auth``（静态 token 访问控制）之上解析身份，供接口做租户隔离。
    """
    require_auth(request, credentials)
    principal = resolve_principal(request)
    # 供后续依赖 / 中间件复用（避免重复解析）。
    request.state.principal = principal
    return principal


def tenant_id_from(request: Request) -> str:
    """从 request.state 取已解析的租户 id；未解析则重新解析（空串表示无作用域）。"""
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is not None:
        return principal.tenant_id
    return resolve_principal(request).tenant_id


# ---- ADR-0019：角色模型与权限校验（§1/§2/§3）----

# 租户内角色等级（ADR-0019 §1）。数值越大权限越高，判定取请求携带的最高角色。
ROLE_RANK: dict[str, int] = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

# ADR-0019 §2：未携带身份令牌（静态 api_token / 匿名）的请求无 roles，
# 按 member 级处理 —— 保留既有静态 token 部署可用，但不授予 admin/owner 能力。
ANONYMOUS_ROLE = "member"


def effective_rank(roles: Iterable[str] | None) -> int:
    """取角色集合的最高等级；空或全部未知时按 ``ANONYMOUS_ROLE`` 级（ADR-0019 §2）。"""
    known = [ROLE_RANK[r] for r in (roles or ()) if r in ROLE_RANK]
    return max(known) if known else ROLE_RANK[ANONYMOUS_ROLE]


def require_role(minimum: str) -> Callable[[Request], Principal]:
    """路由级依赖：要求请求角色不低于 ``minimum``，否则 FIN-1003 FORBIDDEN。

    - 角色取自已验签身份令牌的 ``roles``（ADR-0019 §2：令牌为运行时权威，不回查 DB）；
    - 静态 ``api_token`` / 匿名请求无 roles → 按 member 级，仅可访问 member 及以下能力，
      admin/owner 端点一律拒绝。
    """
    if minimum not in ROLE_RANK:
        raise ValueError(f"unknown role: {minimum}")
    needed = ROLE_RANK[minimum]

    def _dep(request: Request) -> Principal:
        principal: Principal | None = getattr(request.state, "principal", None)
        if principal is None:
            principal = resolve_principal(request)
            request.state.principal = principal
        if effective_rank(principal.roles) < needed:
            raise_for_code(ErrorCode.FORBIDDEN, f"role {minimum} or above required")
        return principal

    return _dep


__all__ = [
    "ANONYMOUS_ROLE",
    "ROLE_RANK",
    "effective_rank",
    "require_auth",
    "require_principal",
    "require_role",
    "resolve_principal",
    "tenant_id_from",
]
