"""登录认证服务单测（ADR-0019 §4）。

覆盖：凭据校验各失败分支（均不区分原因，避免账号枚举）、多租户归属选择、
令牌签发内容（``roles`` 取自 ``user_tenants.role``）。

用内存 SQLite 验证行为（对齐 ``tests/unit/test_repository.py`` 的做法）；真实 MySQL
约束由集成测试覆盖。口令派生用低迭代次数以控制耗时。
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finsage.api.auth_service import AuthService, authenticate
from finsage.api.identity_token import verify_token
from finsage.persistence import base as pbase
from finsage.persistence.models.auth import Tenant, User, UserTenant
from finsage.security import hash_password
from finsage.settings import Settings

_SECRET = "login-test-secret"
_ITERS = 1000
_PASSWORD = "correct-horse"
_EMAIL = "alice@example.com"


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    pbase.Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _seed(
    session: Session,
    *,
    email: str = _EMAIL,
    password: str = _PASSWORD,
    status: str = "active",
    memberships: tuple[tuple[str, str], ...] = (("t1", "admin"),),
) -> User:
    user = User(
        email=email,
        display_name="Alice",
        password_hash=hash_password(password, iterations=_ITERS),
        status=status,
    )
    session.add(user)
    session.flush()  # 生成 user.id 供 user_tenants 关联
    for tenant_id, role in memberships:
        if session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, name=f"tenant-{tenant_id}", status="active"))
        session.add(UserTenant(user_id=user.id, tenant_id=tenant_id, role=role))
    session.commit()
    return user


# ---- authenticate：成功与失败分支 ----


def test_authenticate_success() -> None:
    s = _session()
    _seed(s)
    ctx = authenticate(s, email=_EMAIL, password=_PASSWORD)
    assert ctx is not None
    assert ctx.tenant_id == "t1"
    assert ctx.role == "admin"


def test_authenticate_wrong_password_rejected() -> None:
    s = _session()
    _seed(s)
    assert authenticate(s, email=_EMAIL, password="wrong-password") is None


def test_authenticate_unknown_email_rejected() -> None:
    """账号不存在走 DUMMY_HASH 时序对齐路径，结果同样是失败。"""
    s = _session()
    _seed(s)
    assert authenticate(s, email="nobody@example.com", password=_PASSWORD) is None


def test_authenticate_inactive_user_rejected() -> None:
    s = _session()
    _seed(s, status="disabled")
    assert authenticate(s, email=_EMAIL, password=_PASSWORD) is None


def test_authenticate_user_without_membership_rejected() -> None:
    """用户存在但无租户归属 → 失败（否则无法决定令牌的 tenant_id/role）。"""
    s = _session()
    _seed(s, memberships=())
    assert authenticate(s, email=_EMAIL, password=_PASSWORD) is None


def test_authenticate_user_without_password_hash_rejected() -> None:
    """仅 OAuth 登录（password_hash 为空）的账号不能用口令登录。"""
    s = _session()
    _seed(s)
    user = s.query(User).filter(User.email == _EMAIL).one()
    user.password_hash = None
    s.commit()
    assert authenticate(s, email=_EMAIL, password=_PASSWORD) is None


# ---- 多租户归属选择 ----


def test_authenticate_picks_explicit_tenant() -> None:
    s = _session()
    _seed(s, memberships=(("t1", "admin"), ("t2", "viewer")))
    ctx = authenticate(s, email=_EMAIL, password=_PASSWORD, tenant_id="t2")
    assert ctx is not None
    assert ctx.tenant_id == "t2"
    assert ctx.role == "viewer"  # 角色随租户变化


def test_authenticate_rejects_tenant_not_belonging_to_user() -> None:
    """指定一个该用户不属于的租户 → 失败（防越权选租户）。"""
    s = _session()
    _seed(s, memberships=(("t1", "admin"),))
    assert authenticate(s, email=_EMAIL, password=_PASSWORD, tenant_id="t-other") is None


def test_authenticate_defaults_to_earliest_membership() -> None:
    """未指定租户时选择稳定可预期（按 created_at 排序取最早）。"""
    s = _session()
    _seed(s, memberships=(("t1", "admin"), ("t2", "viewer")))
    ctx = authenticate(s, email=_EMAIL, password=_PASSWORD)
    assert ctx is not None
    assert ctx.tenant_id == "t1"


# ---- AuthService：令牌签发 ----


def test_login_issues_token_carrying_role() -> None:
    """令牌 roles 必须来自 user_tenants.role（ADR-0019 §2：DB 是签发源）。"""
    s = _session()
    _seed(s)
    service = AuthService(Settings(identity_token_secret=_SECRET))
    result = service.login(email=_EMAIL, password=_PASSWORD, session=s)
    assert result is not None
    ctx, token, expires_in = result
    assert expires_in == 3600

    payload = verify_token(token, secret=_SECRET)
    assert payload is not None
    assert payload["user_id"] == ctx.user_id
    assert payload["tenant_id"] == "t1"
    assert payload["roles"] == ["admin"]


def test_login_rejects_bad_credentials() -> None:
    s = _session()
    _seed(s)
    service = AuthService(Settings(identity_token_secret=_SECRET))
    assert service.login(email=_EMAIL, password="wrong", session=s) is None


def test_login_fails_without_identity_secret() -> None:
    """未配置密钥则无法签发 —— 诚实失败，不降级为无身份放行。"""
    s = _session()
    _seed(s)
    service = AuthService(Settings(identity_token_secret=""))
    assert service.login(email=_EMAIL, password=_PASSWORD, session=s) is None
