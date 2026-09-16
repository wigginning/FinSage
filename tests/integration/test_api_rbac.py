"""ADR-0019 RBAC 执行点测试：角色判定 + 端点权限矩阵（离线，不依赖 DB/模型）。

覆盖：
- ``effective_rank``：角色等级、空 roles（静态 token/匿名 → member 级）、未知角色、取最高；
- ``require_role``：viewer 令牌被写端点拒绝（FIN-1003）、member/admin/owner 放行；
- 读端点对 viewer 放行（viewer 可读不可写，即权限矩阵最低档）；
- 静态 ``api_token``（无身份令牌）按 member 级，既有部署行为不变（防回归）。

不依赖真实 DB / Milvus / 模型：注入替身 runner 与内存存储。
"""
from __future__ import annotations

import httpx
import pytest

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app
from finsage.api.auth import ROLE_RANK, effective_rank, require_role
from finsage.api.identity_token import sign_token
from finsage.api.tasks import TaskManager
from finsage.settings import Settings

_SECRET = "rbac-test-secret"


class FakeRunner:
    """成功替身：直接完成，不触达真实检索/计算。"""

    async def run(self, kind: str, *, input_, handle) -> None:
        handle.result = {"answer": "ok", "kind": kind}


def _make_app(*, api_token: str = "", identity_secret: str = _SECRET):
    settings = Settings(api_token=api_token, identity_token_secret=identity_secret)
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


def _token(*roles: str) -> str:
    """签发带指定角色的身份令牌。"""
    return sign_token(user_id="u1", tenant_id="t1", secret=_SECRET, roles=list(roles))


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---- effective_rank：ADR-0019 §1/§2 ----


def test_effective_rank_known_roles():
    assert effective_rank(["viewer"]) == ROLE_RANK["viewer"]
    assert effective_rank(["member"]) == ROLE_RANK["member"]
    assert effective_rank(["admin"]) == ROLE_RANK["admin"]
    assert effective_rank(["owner"]) == ROLE_RANK["owner"]
    # 等级递增，保证权限矩阵的比较语义成立。
    assert ROLE_RANK["viewer"] < ROLE_RANK["member"] < ROLE_RANK["admin"] < ROLE_RANK["owner"]


def test_effective_rank_empty_falls_back_to_member():
    """ADR-0019 §2：静态 token / 匿名无 roles → member 级（保留既有部署可用）。"""
    assert effective_rank([]) == ROLE_RANK["member"]
    assert effective_rank(None) == ROLE_RANK["member"]


def test_effective_rank_unknown_role_falls_back_to_member():
    """未知角色不提权：按 member 级处理（避免拼错的角色名意外获得 admin）。"""
    assert effective_rank(["superuser"]) == ROLE_RANK["member"]


def test_effective_rank_takes_highest():
    assert effective_rank(["viewer", "admin"]) == ROLE_RANK["admin"]
    assert effective_rank(["member", "owner", "viewer"]) == ROLE_RANK["owner"]


def test_require_role_unknown_minimum_rejected():
    """最小角色名写错应立刻失败（配置错误早暴露，而非静默放行）。"""
    with pytest.raises(ValueError):
        require_role("boss")


# ---- 端点权限矩阵：ADR-0019 §1/§3 ----


async def test_viewer_cannot_write_chat():
    """viewer 令牌被写端点拒绝 → 403 FIN-1003。"""
    async with _client(_make_app()) as c:
        resp = await c.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {_token('viewer')}"},
        )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FIN-1003"


async def test_member_can_write_chat():
    async with _client(_make_app()) as c:
        resp = await c.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": f"Bearer {_token('member')}"},
        )
    assert resp.status_code == 200


async def test_admin_and_owner_can_write_chat():
    """高角色向下兼容：admin/owner 具备 member 能力。"""
    for role in ("admin", "owner"):
        async with _client(_make_app()) as c:
            resp = await c.post(
                "/api/v1/chat",
                json={"message": "hi"},
                headers={"Authorization": f"Bearer {_token(role)}"},
            )
        assert resp.status_code == 200, role


async def test_viewer_can_read_tasks():
    """读端点对 viewer 放行（viewer 可读不可写）。"""
    async with _client(_make_app()) as c:
        resp = await c.get(
            "/api/v1/tasks",
            headers={"Authorization": f"Bearer {_token('viewer')}"},
        )
    assert resp.status_code == 200


async def test_static_token_keeps_member_access():
    """防回归：静态 api_token（无法解析为身份令牌 → 匿名 member 级）仍可写。"""
    app = _make_app(api_token="static-token")
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": "Bearer static-token"},
        )
    assert resp.status_code == 200


async def test_static_token_denied_at_admin_endpoint():
    """ADR-0019 §2：静态 token 不获 admin/owner 能力（此处直接验证依赖判定）。"""
    from fastapi import Request

    from finsage.exceptions import FinSageError

    app = _make_app(api_token="static-token")
    dep = require_role("admin")
    # 构造一个携带静态 token 的请求上下文，依赖应抛 FIN-1003。
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer static-token")],
        "app": app,
    }
    request = Request(scope)
    with pytest.raises(FinSageError) as exc:
        dep(request)
    assert exc.value.code.value == "FIN-1003"
