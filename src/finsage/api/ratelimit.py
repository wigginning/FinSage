"""API 层限流依赖（ADR-0020）。

在既有 ``FinRedis.rate_limit_add``（固定窗口 ``INCR`` + 首次 ``EXPIRE``）之上提供
路由级依赖：

- **作用域（§2）**：优先按身份（``tenant_id``/``user_id``，取自已验签身份令牌）；
  无身份令牌时回退按源 IP，防止未鉴权重端点被单 IP 打满。
- **降级（§3）**：Redis 不可用 / 未装配时默认 **fail-open**（放行 + warning，保可用性），
  ``rate_limit_fail_closed=True`` 时按 ``FIN-1005`` 拒绝（保护后端资源）。
- **接线（§4）**：只作用于重端点，且仅在**提交时**限流（SSE 流过程不二次限）。

已知限制：固定窗口在窗口交界处存在最多 2 倍突发（ADR-0020 §1 已披露）；
令牌桶 / 滑动窗口列为后续增强，不在本次实现范围。
"""
from __future__ import annotations

import logging
from typing import cast

from fastapi import Request
from redis.exceptions import RedisError

from finsage.api.auth import resolve_principal
from finsage.exceptions import ErrorCode, RateLimitedError, raise_for_code
from finsage.persistence.redis import FinRedis
from finsage.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# 内置默认限额（路由路径 -> (limit, window_seconds)）。
# 优先级：显式参数 > settings.rate_limit_routes > 本表 > _FALLBACK。
_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "/api/v1/chat": (60, 60),
    "/api/v1/research": (30, 60),
    "/api/v1/companies": (120, 60),
}
_FALLBACK = (60, 60)


def _limits_for(path: str, settings: Settings) -> tuple[int, int]:
    """取路由限额：配置覆盖优先 → 内置默认 → 兜底。"""
    override = (settings.rate_limit_routes or {}).get(path) or {}
    if "limit" in override and "window_seconds" in override:
        return int(override["limit"]), int(override["window_seconds"])
    return _DEFAULT_LIMITS.get(path, _FALLBACK)


def scope_key(request: Request) -> str:
    """限流作用域键（ADR-0020 §2）：身份优先，无身份回退源 IP。"""
    principal = getattr(request.state, "principal", None) or resolve_principal(request)
    if principal.user_id:
        return f"tenant:{principal.tenant_id}:user:{principal.user_id}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _redis(request: Request) -> FinRedis | None:
    """取运行态 Redis 封装（``Deps.redis``）；未装配返回 None。

    用**鸭子类型**判定而非 ``isinstance``：只要具备计数接口就视为可用。
    避免把自定义/替身客户端误判为"未装配"而静默绕过限流（那是危险的 fail-open）。
    """
    deps = getattr(request.app.state, "deps", None)
    redis = getattr(deps, "redis", None) if deps is not None else None
    if redis is not None and hasattr(redis, "rate_limit_add") and hasattr(redis, "ttl"):
        return cast("FinRedis", redis)
    return None


def _on_unavailable(settings: Settings, reason: str) -> None:
    """限流器自身不可用时的降级判定（ADR-0020 §3）。

    fail-open（默认）：记录 warning 并放行——限流器故障不应拖垮业务可用性。
    fail-closed：按 FIN-1005 拒绝，以保护后端资源（建议多租户生产启用）。
    """
    if settings.rate_limit_fail_closed:
        raise_for_code(ErrorCode.RATE_LIMITED)
    logger.warning("rate limit unavailable (%s) → fail-open 放行", reason)


def require_rate_limit(*, limit: int | None = None, window_seconds: int | None = None):
    """路由级依赖：对当前作用域做固定窗口限流，超限抛 ``FIN-1005``（429 + Retry-After）。

    - ``limit``/``window_seconds`` 显式传入时优先（便于测试与特化端点）；
    - 否则按 ``settings.rate_limit_routes`` → 内置默认 → 兜底；
    - ``settings.rate_limit_enabled=False`` 时直接放行（等同不限流）。
    """

    def _dep(request: Request) -> None:
        settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
        if not settings.rate_limit_enabled:
            return
        if limit is not None and window_seconds is not None:
            lim, win = limit, window_seconds
        else:
            lim, win = _limits_for(request.url.path, settings)

        client = _redis(request)
        if client is None:
            _on_unavailable(settings, "redis 未装配")
            return

        key = f"ratelimit:{scope_key(request)}:{request.url.path}"
        try:
            count = int(client.rate_limit_add(key, win))
        except (RedisError, OSError) as exc:
            _on_unavailable(settings, f"redis 异常 {type(exc).__name__}")
            return

        if count > lim:
            retry_after = win
            try:
                remaining = int(client.ttl(key))
                if remaining > 0:
                    retry_after = remaining
            except (RedisError, OSError, TypeError):
                pass  # ttl 失败不影响限流结论，退回用窗口长度
            # 可观测（ADR-0020 §4）：被限流是需要关注的事件，便于运维定位配额问题。
            logger.warning(
                "rate limit exceeded: path=%s count=%d limit=%d retry_after=%ds",
                request.url.path,
                count,
                lim,
                retry_after,
            )
            raise RateLimitedError(retry_after=retry_after)

    return _dep


__all__ = ["require_rate_limit", "scope_key"]
