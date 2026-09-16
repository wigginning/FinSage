"""账号开通库函数单测（ADR-0019 §4 的运营依赖）。

用内存 SQLite 验证 ``provision_user`` 的"取或建"语义：用户/租户/关联各自可独立复用，
非法输入与覆盖既有账号须被拒绝，重置口令须生效。口令派生经 monkeypatch 降迭代次数，
仅控制单测耗时，不改变行为。

不需 MySQL / FIN_DB_URL（与 ``test_auth_service.py`` 一致，用内存 SQLite）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as ORMSession

from finsage.persistence import base as pbase
from finsage.persistence.models.auth import User, UserTenant
from finsage.provisioning import (
    MIN_PASSWORD_LENGTH,
    VALID_ROLES,
    ProvisionError,
    provision_user,
)
from finsage.security import hash_password, verify_password

_FAST_ITERS = 1000


@pytest.fixture()
def session(monkeypatch) -> ORMSession:
    # 降派生开销：provisioning 通过模块命名空间引用 hash_password，patch 该名即可。
    monkeypatch.setattr(
        "finsage.provisioning.hash_password",
        lambda pw, *, iterations=_FAST_ITERS: hash_password(pw, iterations=iterations),
    )
    engine = create_engine("sqlite:///:memory:")
    pbase.Base.metadata.create_all(engine)
    return ORMSession(engine, expire_on_commit=False)


def _user_row(session: ORMSession, user_id: str) -> User:
    return session.get(User, user_id)


def _membership(session: ORMSession, user_id: str, tenant_id: str) -> UserTenant | None:
    return (
        session.query(UserTenant)
        .filter(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
        .one_or_none()
    )


# ---- 新建：三项都建出来 ----

def test_provision_creates_user_tenant_and_membership(session: ORMSession) -> None:
    result = provision_user(
        session,
        email="alice@corp.com",
        password="long-enough-pass",
        tenant_name="acme",
        role="admin",
    )
    assert result.created_user is True
    assert result.created_tenant is True
    assert result.created_membership is True
    assert result.role == "admin"
    assert result.tenant_name == "acme"
    assert result.user_id and result.tenant_id

    user = _user_row(session, result.user_id)
    assert user is not None
    assert user.email == "alice@corp.com"  # 已归一化为小写
    assert user.password_hash
    assert verify_password("long-enough-pass", user.password_hash)

    member = _membership(session, result.user_id, result.tenant_id)
    assert member is not None
    assert member.role == "admin"


def test_provision_normalizes_email_lowercase(session: ORMSession) -> None:
    result = provision_user(
        session,
        email="Bob@Corp.COM",
        password="long-enough-pass",
        tenant_name="acme",
    )
    user = _user_row(session, result.user_id)
    assert user.email == "bob@corp.com"


def test_provision_default_display_name_from_email_prefix(session: ORMSession) -> None:
    result = provision_user(
        session, email="carol@corp.com", password="long-enough-pass", tenant_name="acme"
    )
    user = _user_row(session, result.user_id)
    assert user.display_name == "carol"


# ---- 复用：租户独立复用，用户独立复用 ----

def test_reuses_existing_tenant(session: ORMSession) -> None:
    r1 = provision_user(
        session, email="a@corp.com", password="long-enough-pass", tenant_name="acme", role="admin"
    )
    r2 = provision_user(
        session, email="b@corp.com", password="long-enough-pass", tenant_name="acme", role="member"
    )
    assert r2.created_tenant is False
    assert r2.tenant_id == r1.tenant_id

    # 第二个用户也归属到同一租户、角色为各自的 member
    member = _membership(session, r2.user_id, r1.tenant_id)
    assert member is not None
    assert member.role == "member"


def test_reuses_existing_user_without_reset_is_rejected(session: ORMSession) -> None:
    provision_user(
        session, email="a@corp.com", password="long-enough-pass", tenant_name="acme"
    )
    with pytest.raises(ProvisionError):
        provision_user(
            session, email="a@corp.com", password="other-pass-123", tenant_name="acme"
        )


def test_reset_password_updates_hash_and_reactivates(session: ORMSession) -> None:
    r1 = provision_user(
        session, email="a@corp.com", password="first-pass-123", tenant_name="acme"
    )
    old_user = _user_row(session, r1.user_id)
    old_hash = old_user.password_hash
    assert old_user.status == "active"

    # 模拟禁用后再重置：应同时更新口令并重新激活
    old_user.status = "disabled"
    session.flush()

    r2 = provision_user(
        session,
        email="a@corp.com",
        password="second-pass-456",
        tenant_name="acme",
        reset_password=True,
    )
    assert r2.created_user is False
    user = _user_row(session, r1.user_id)
    assert user.password_hash != old_hash
    assert user.status == "active"
    assert verify_password("second-pass-456", user.password_hash)
    assert not verify_password("first-pass-123", user.password_hash)


def test_existing_membership_role_update(session: ORMSession) -> None:
    r = provision_user(
        session, email="a@corp.com", password="long-enough-pass", tenant_name="acme", role="member"
    )
    assert r.created_membership is True

    # 再次对同一租户开户并改角色：关联已存在 → 更新角色，不新建
    r2 = provision_user(
        session,
        email="a@corp.com",
        password="long-enough-pass",
        tenant_name="acme",
        role="admin",
        reset_password=True,
    )
    assert r2.created_membership is False
    member = _membership(session, r.user_id, r.tenant_id)
    assert member is not None
    assert member.role == "admin"


# ---- 校验失败分支 ----

def test_invalid_role_rejected(session: ORMSession) -> None:
    with pytest.raises(ProvisionError):
        provision_user(
            session,
            email="a@corp.com",
            password="long-enough-pass",
            tenant_name="acme",
            role="superuser",
        )


def test_invalid_email_rejected(session: ORMSession) -> None:
    with pytest.raises(ProvisionError):
        provision_user(
            session, email="not-an-email", password="long-enough-pass", tenant_name="acme"
        )


def test_short_password_rejected(session: ORMSession) -> None:
    with pytest.raises(ProvisionError):
        provision_user(
            session, email="a@corp.com", password="short", tenant_name="acme"
        )


def test_empty_tenant_rejected(session: ORMSession) -> None:
    with pytest.raises(ProvisionError):
        provision_user(
            session, email="a@corp.com", password="long-enough-pass", tenant_name="   "
        )


def test_valid_roles_aligned_with_role_rank(session: ORMSession) -> None:
    # 角色合法集合应与 RBAC 角色模型一致（单一来源在 api.auth.ROLE_RANK）。
    from finsage.api.auth import ROLE_RANK

    assert set(VALID_ROLES) == set(ROLE_RANK)
    assert MIN_PASSWORD_LENGTH >= 8
