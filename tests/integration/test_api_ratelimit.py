"""ADR-0020 限流回归测试：固定窗口 / 作用域 / 降级 / 错误契约（fakeredis，离线）。

覆盖：
- 固定窗口计数：未超限放行、超限返回 ``429 FIN-1005`` + ``Retry-After``；
- 作用域（§2）：按身份（tenant/user）独立计数；无身份令牌回退按源 IP；
- 降级（§3）：Redis 不可用时默认 fail-open 放行，``fail_closed=True`` 时拒绝；
- 开关：``rate_limit_enabled=False`` 时完全不限流；
- 错误契约（§7）：``FIN-1005`` 与 ``FIN-2003``（上游限流）语义区分。

不依赖真实 Redis / DB / 模型：注入 fakeredis 与替身 runner。
"""
from __future__ import annotations

import fakeredis
import httpx
import pytest
from redis.exceptions import RedisError

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app
from finsage.api.identity_token import sign_token
from finsage.api.ratelimit import scope_key
from finsage.api.tasks import TaskManager
from finsage.persistence.redis import FinRedis
from finsage.settings import Settings

_SECRET = "ratelimit-test-secret"
_LIMIT = 2  # 窗口内允许的次数（第 3 次应被拒）


class FakeRunner:
    async def run(self, kind: str, *, input_, handle) -> None:
        handle.result = {"answer": "ok", "kind": kind}


class FaultyRedis:
    """替身：计数与 ttl 均抛 Redis 异常（模拟 Redis 不可用）。"""

    def rate_limit_add(self, key: str, window_seconds: int, step: int = 1) -> int:
        raise RedisError("redis is down")

    def ttl(self, key: str) -> int:
        raise RedisError("redis is down")


def _fake_redis() -> FinRedis:
    server = fakeredis.FakeServer()
    return FinRedis(client=fakeredis.FakeRedis(server=server, decode_responses=True))


def _make_app(
    *,
    api_token: str = "",
    identity_secret: str = _SECRET,
    redis: object | None = "auto",
    **settings_kwargs,
):
    """``redis`` 为 ``"auto"`` 时注入一个新的 fakeredis；``None`` 表示未装配。"""
    settings = Settings(
        api_token=api_token,
        identity_token_secret=identity_secret,
        rate_limit_routes={"/api/v1/chat": {"limit": _LIMIT, "window_seconds": 60}},
        **settings_kwargs,
    )
    audit = AuditStore()
    deps = Deps(
        settings=settings,
        task_manager=TaskManager(),
        runner=FakeRunner(),
        files=FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
        redis=_fake_redis() if redis == "auto" else redis,
    )
    return create_app(settings=settings, deps=deps)


def _token(user: str = "u1", tenant: str = "t1") -> str:
    return sign_token(user_id=user, tenant_id=tenant, secret=_SECRET, roles=["member"])


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _post_chat(client: httpx.AsyncClient, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.post("/api/v1/chat", json={"message": "hi"}, headers=headers)


# ---- 固定窗口计数 + 错误契约（ADR-0020 §1/§7）----


async def test_requests_within_limit_allowed():
    async with _client(_make_app()) as c:
        for _ in range(_LIMIT):
            resp = await _post_chat(c, _token())
            assert resp.status_code == 200


async def test_exceeding_limit_returns_429_with_retry_after():
    async with _client(_make_app()) as c:
        for _ in range(_LIMIT):
            assert (await _post_chat(c, _token())).status_code == 200
        resp = await _post_chat(c, _token())
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "FIN-1005"
    assert int(resp.headers["Retry-After"]) > 0


async def test_rate_limit_disabled_passes_through():
    """显式关闭时行为等同不限流。"""
    async with _client(_make_app(rate_limit_enabled=False)) as c:
        for _ in range(_LIMIT + 3):
            assert (await _post_chat(c, _token())).status_code == 200


# ---- 作用域（ADR-0020 §2）----


async def test_quota_is_per_identity():
    """不同用户独立计数：u1 超限不影响 u2。"""
    async with _client(_make_app()) as c:
        for _ in range(_LIMIT):
            assert (await _post_chat(c, _token("u1"))).status_code == 200
        assert (await _post_chat(c, _token("u1"))).status_code == 429
        assert (await _post_chat(c, _token("u2"))).status_code == 200


async def test_scope_key_prefers_identity():
    from fastapi import Request

    app = _make_app()
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {_token()}".encode())],
            "app": app,
            "client": ("1.2.3.4", 1234),
        }
    )
    assert scope_key(request) == "tenant:t1:user:u1"


async def test_scope_key_falls_back_to_ip_without_identity():
    """无身份令牌（静态 token）→ 按源 IP 限流，防未鉴权重端点被打满。"""
    from fastapi import Request

    app = _make_app(api_token="static-token")
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer static-token")],
            "app": app,
            "client": ("1.2.3.4", 1234),
        }
    )
    assert scope_key(request) == "ip:1.2.3.4"


# ---- 降级策略（ADR-0020 §3）----


async def test_redis_unavailable_fails_open_by_default():
    """默认 fail-open：限流器自身故障不拖垮业务可用性。"""
    async with _client(_make_app(redis=FaultyRedis())) as c:
        for _ in range(_LIMIT + 3):
            assert (await _post_chat(c, _token())).status_code == 200


async def test_redis_unavailable_fails_closed_when_configured():
    """fail_closed=True：Redis 不可用时按 FIN-1005 拒绝，保护后端资源。"""
    app = _make_app(redis=FaultyRedis(), rate_limit_fail_closed=True)
    async with _client(app) as c:
        resp = await _post_chat(c, _token())
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "FIN-1005"


async def test_redis_not_configured_fails_open_by_default():
    """未装配 Redis（redis=None）时同样走降级路径，默认放行。"""
    async with _client(_make_app(redis=None)) as c:
        for _ in range(_LIMIT + 3):
            assert (await _post_chat(c, _token())).status_code == 200


async def test_redis_not_configured_fails_closed_when_configured():
    app = _make_app(redis=None, rate_limit_fail_closed=True)
    async with _client(app) as c:
        resp = await _post_chat(c, _token())
    assert resp.status_code == 429


# ---- 错误契约：FIN-1005 与 FIN-2003 语义区分（ADR-0020 §7）----


def test_fin_1005_distinct_from_fin_2003():
    """FIN-1005 = 客户端请求超限；FIN-2003 = 上游数据源限流。两者不得混用。"""
    from finsage.exceptions import ErrorCode

    assert ErrorCode.RATE_LIMITED == "FIN-1005"
    assert ErrorCode.PROVIDER_RATE_LIMITED == "FIN-2003"
    assert ErrorCode.RATE_LIMITED != ErrorCode.PROVIDER_RATE_LIMITED


@pytest.mark.parametrize("code", ["FIN-1005", "FIN-2003"])
def test_both_rate_limit_codes_map_to_429(code):
    from finsage.exceptions import ErrorCode, raise_for_code

    with pytest.raises(Exception) as exc:  # noqa: B017 - 断言两类均抛 FIN 异常
        raise_for_code(ErrorCode(code))
    assert exc.value.http_status == 429
