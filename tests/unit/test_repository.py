"""仓储层行为测试（T104）。

覆盖：白名单字段过滤拒绝非法字段、租户最小权限作用域、仓储返回 ORM 域对象而非裸 dict。
使用内存 SQLite 验证行为（MySQL 特有类型在 create_all 下可用；真实 MySQL 约束/索引由
T105 集成测试覆盖）。
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finsage.persistence import base as pbase
from finsage.persistence.models.rag import Document
from finsage.persistence.models.research import ResearchTask
from finsage.persistence.repositories import (
    DocumentRepository,
    ResearchTaskRepository,
)


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    pbase.Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _add_task(session: Session, *, tenant_id: str, status: str, query: str) -> ResearchTask:
    task = ResearchTask(
        tenant_id=tenant_id,
        session_id="session-x",
        type="research_qa",
        query=query,
        status=status,
        trace_id=f"tr_{query}",
    )
    session.add(task)
    session.flush()
    return task


def test_filter_rejects_non_whitelist_field() -> None:
    """非白名单字段等值过滤应抛 ValueError（安全：最小暴露面）。"""
    session = _make_session()
    repo = ResearchTaskRepository(session)
    raised = False
    try:
        repo.filter(query="猜猜看")  # query 不在 allow_filters
    except ValueError:
        raised = True
    finally:
        session.close()
    assert raised


def test_filter_allows_whitelist_field() -> None:
    """白名单字段可正常过滤，且返回 ORM 域对象。"""
    session = _make_session()
    _add_task(session, tenant_id="t1", status="pending", query="q1")
    session.commit()

    repo = ResearchTaskRepository(session)
    found = repo.find_many(status="pending")
    assert len(found) == 1
    assert isinstance(found[0], ResearchTask)  # 域对象，非 dict
    session.close()


def test_tenant_scoping_isolates_tenants() -> None:
    """注入租户后，list/get 自动附加 tenant_id 过滤（最小权限）。"""
    session = _make_session()
    task_a = _add_task(session, tenant_id="tenant-a", status="pending", query="qa")
    task_b = _add_task(session, tenant_id="tenant-b", status="pending", query="qb")
    session.commit()

    repo_a = ResearchTaskRepository(session, tenant_id="tenant-a")
    found = repo_a.find_many(status="pending")
    assert [t.tenant_id for t in found] == ["tenant-a"]
    # get 同样受作用域约束：跨租户对象查不到
    assert repo_a.get(task_b.id) is None
    # 本租户对象可查
    assert repo_a.get(task_a.id) is not None
    session.close()


def test_get_returns_domain_object() -> None:
    """按主键 get 返回域对象（或 None），非裸 dict。"""
    session = _make_session()
    task = _add_task(session, tenant_id="t1", status="running", query="q2")
    session.commit()

    repo = ResearchTaskRepository(session)
    got = repo.get(task.id)
    assert isinstance(got, ResearchTask)
    assert got.query == "q2"
    assert repo.get("no-such-id") is None
    session.close()


def test_document_repo_tenant_scope() -> None:
    """DocumentRepository 具备租户作用域，支持按 sha256 定位。"""
    session = _make_session()
    session.add(
        Document(
            tenant_id="t-a",
            title="doc",
            filename="doc.pdf",
            size=1024,
            source_type="financial",
            sha256="abc123",
            authority_tier=1,
            status="ingested",
        )
    )
    session.commit()

    repo = DocumentRepository(session, tenant_id="t-a")
    doc = repo.find_by_sha256("abc123")
    assert doc is not None
    assert doc.tenant_id == "t-a"
    session.close()
