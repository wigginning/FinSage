"""登录端点集成测试（ADR-0019 §4）—— 聚焦 **HTTP 层契约**。

真实的凭据校验与令牌签发依赖 MySQL，在单测环境不可用（8 项 MySQL 集成测试被 skip），
因此这里用替身 ``AuthService`` 验证 HTTP 契约；业务逻辑由
``tests/unit/test_auth_service.py``（内存 SQLite）与 ``tests/unit/test_security.py`` 覆盖。
"""
from __future__ import annotations

import httpx
import pytest

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app, routes_auth
from finsage.api.auth_service import AuthContext
from finsage.api.tasks import TaskManager
from finsage.settings import Settings

_SECRET = "login-route-test-secret"


class FakeRunner:
    async def run(self, kind: str, *, input_, handle) -> None:
        handle.result = {"answer": "ok"}


class FakeAuthService:
    """替身：仅 ``ok@example.com`` 登录成功，其余一律失败。"""

    def __init__(self, settings: object = None) -> None:
        pass

    def login(self, *, email: str, password: str, tenant_id: str | None = None, session=None):
        if email == "ok@example.com" and password == "good-pass":
            return AuthContext(user_id="u1", tenant_id="t1", role="admin"), "token-abc", 3600
        return None


@pytest.fixture
def patched_service(monkeypatch):
    monkeypatch.setattr(routes_auth, "AuthService", FakeAuthService)
    return None


def _make_app(**settings_kwargs):
    # setdefault：允许测试显式把 identity_token_secret 置空（测"未配置密钥"场景）。
    settings_kwargs.setdefault("identity_token_secret", _SECRET)
    settings = Settings(**settings_kwargs)
    audit = AuditStore()
    deps = Deps(
        settings=settings,
        task_manager=TaskManager(),
        runner=FakeRunner(),
        files=FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
    )
    return create_app(settings=settings, deps=deps)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_login_returns_token(patched_service):
    async with _client(_make_app()) as c:
        resp = await c.post(
            "/api/v1/auth/login", json={"email": "ok@example.com", "password": "good-pass"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "token-abc"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user_id"] == "u1"
    assert body["tenant_id"] == "t1"
    assert body["role"] == "admin"


async def test_login_rejects_bad_credentials(patched_service):
    """失败一律 FIN-1002 —— 不区分账号不存在 / 口令错误（防账号枚举）。"""
    async with _client(_make_app()) as c:
        resp = await c.post(
            "/api/v1/auth/login", json={"email": "ok@example.com", "password": "bad-pass"}
        )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "FIN-1002"


async def test_login_route_needs_no_bearer_token(patched_service):
    """登录端点不套 require_auth —— 否则获取令牌前先要有令牌，形成死锁。"""
    async with _client(_make_app(api_token="static-token")) as c:
        resp = await c.post(
            "/api/v1/auth/login",
            json={"email": "ok@example.com", "password": "good-pass"},
            # 故意不带 Authorization 头
        )
    assert resp.status_code == 200


async def test_login_requires_configured_identity_secret(patched_service):
    """未配置身份令牌密钥 → 诚实失败（500），绝不降级为无身份放行。"""
    async with _client(_make_app(identity_token_secret="")) as c:
        resp = await c.post(
            "/api/v1/auth/login", json={"email": "ok@example.com", "password": "good-pass"}
        )
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "FIN-6001"


async def test_login_rejects_empty_payload(patched_service):
    """入参校验失败 → FIN-1001（400）。"""
    async with _client(_make_app()) as c:
        resp = await c.post("/api/v1/auth/login", json={})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FIN-1001"


async def test_login_rejects_oversized_password(patched_service):
    """超长口令被拒（防 PBKDF2 CPU DoS）。"""
    async with _client(_make_app()) as c:
        resp = await c.post(
            "/api/v1/auth/login",
            json={"email": "ok@example.com", "password": "x" * 5000},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "FIN-1001"
