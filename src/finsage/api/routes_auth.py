"""登录路由（ADR-0019 §4）。

``/auth/login`` **不套** router 级 ``require_auth`` —— 登录本身就是获取令牌的手段，
要求先持有令牌会形成死锁。本路由的安全性由"凭据校验"承担：
校验失败一律返回 FIN-1002，不泄露账号是否存在。

同步 DB I/O（MySQL 仓储）经 ``asyncio.to_thread`` 移入线程池，避免阻塞事件循环
（与 ``routes.py`` 既有约定一致）。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from finsage.api.auth_service import AuthService
from finsage.api.schemas import LoginRequest, LoginResponse
from finsage.exceptions import ErrorCode, raise_for_code
from finsage.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _settings(request: Request) -> Settings:
    """优先取 app.state.settings（供测试/子应用注入），否则回退全局配置。"""
    return getattr(request.app.state, "settings", None) or get_settings()


@router.post("/login", response_model=LoginResponse, summary="登录并获取身份令牌")
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    """校验邮箱 + 口令，签发签名身份令牌（ADR-0019 §4）。

    令牌载荷为 ``{user_id, tenant_id, roles, exp}``，其中 ``roles`` 取自
    ``user_tenants.role``（DB 为签发源，令牌为运行时权威 —— ADR-0019 §2）。

    失败**一律**返回 FIN-1002：不区分"账号不存在 / 口令错误 / 账号未激活 /
    无租户归属 / 指定租户不属于该用户"，避免账号枚举。
    """
    settings = _settings(request)
    if not settings.identity_token_secret:
        # 未配置密钥则无法签发 —— 诚实失败，绝不降级为"无身份放行"。
        raise_for_code(ErrorCode.INTERNAL_ERROR, "identity token secret not configured")

    service = AuthService(settings)
    # PBKDF2 派生 + 同步 DB I/O：移入线程池，避免阻塞事件循环。
    result = await asyncio.to_thread(
        service.login, email=req.email, password=req.password, tenant_id=req.tenant_id
    )
    if result is None:
        raise_for_code(ErrorCode.AUTH_REQUIRED, "invalid credentials")

    ctx, token, expires_in = result
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        role=ctx.role,
    )


__all__ = ["router"]
