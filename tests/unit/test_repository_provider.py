"""P0 TenantScopedRepository 接线：按请求租户构造仓储并自动过滤（内存 SQLite）。"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finsage.persistence import base as pbase
from finsage.persistence.models.rag import Document
from finsage.persistence.repositories.provider import TenantRepositoryProvider


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    pbase.Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def test_provider_document_repo_scoped_to_tenant():
    session = _make_session()
    session.add(
        Document(
            tenant_id="t-a",
            title="A",
            filename="a.pdf",
            size=1,
            source_type="upload",
            sha256="sha-a",
            authority_tier=0,
            status="ingested",
        )
    )
    session.add(
        Document(
            tenant_id="t-b",
            title="B",
            filename="b.pdf",
            size=1,
            source_type="upload",
            sha256="sha-b",
            authority_tier=0,
            status="ingested",
        )
    )
    session.commit()

    provider = TenantRepositoryProvider(tenant_id="t-a")
    repo = provider.document(session)
    all_a = repo.find_many()
    assert all_a and all(a.tenant_id == "t-a" for a in all_a)
    assert len(all_a) == 1  # 只返回本租户文档
    # 跨租户按 sha256 查不到。
    assert repo.find_by_sha256("sha-b") is None
    session.close()


def test_provider_without_tenant_returns_all():
    """无租户作用域（系统级）时不附加过滤。"""
    session = _make_session()
    session.add(
        Document(
            tenant_id="t-a",
            title="A",
            filename="a.pdf",
            size=1,
            source_type="upload",
            sha256="sha-a",
            authority_tier=0,
            status="ingested",
        )
    )
    session.add(
        Document(
            tenant_id="t-b",
            title="B",
            filename="b.pdf",
            size=1,
            source_type="upload",
            sha256="sha-b",
            authority_tier=0,
            status="ingested",
        )
    )
    session.commit()

    provider = TenantRepositoryProvider(tenant_id=None)
    repo = provider.document(session)
    assert len(repo.find_many()) == 2
    session.close()


def test_provider_exposes_tenant_scoped_repos():
    """各域仓储构造器存在且可调用（构造不连库即可验证）。"""
    provider = TenantRepositoryProvider(tenant_id="t1")
    for ctor in (
        provider.document,
        provider.evidence,
        provider.research_task,
        provider.session_repo,
        provider.audit,
        provider.provider_config,
    ):
        assert callable(ctor)
