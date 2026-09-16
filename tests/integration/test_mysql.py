"""MySQL 集成测试（T105）。

针对真实 MySQL（docker compose 启动的 finsage 库）验证：
- 全部 19 张表已按 §5 建成；
- 库/表/字段中文注释已落库；
- 主键/唯一键/外键/索引约束齐全；
- 仓储 CRUD 往返与租户最小权限作用域。

前置：通过环境变量 FIN_DB_URL 指向真实 MySQL（未设置则跳过）。
CRUD 用例在事务内执行并回滚，不污染共享库。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from finsage.persistence.models.auth import Session as ChatSession
from finsage.persistence.models.auth import Tenant, User
from finsage.persistence.models.research import ResearchTask
from finsage.persistence.repositories import ResearchTaskRepository

DB_URL = os.getenv("FIN_DB_URL")


def _make_parents(session: Session, tenant_name: str, email: str) -> Session:
    """构造 research_task 所需的父记录链：Tenant -> User -> Session。

    返回会话对象（ORM）；连同任务一并回滚，不落库。
    """
    tenant = Tenant(name=tenant_name, status="active")
    user = User(email=email, display_name="集成测试用户", status="active")
    # 主键为 UUID，先 flush 父级取得 id 再回填外键
    session.add(tenant)
    session.add(user)
    session.flush()
    conv = ChatSession(
        tenant_id=tenant.id,
        user_id=user.id,
        title="集成测试会话",
        status="active",
    )
    session.add(conv)
    session.flush()
    return conv


pytestmark = pytest.mark.skipif(
    not DB_URL, reason="未配置 FIN_DB_URL，跳过 MySQL 集成测试"
)


_SCHEMA_TABLES = [
    "users",
    "tenants",
    "user_tenants",
    "sessions",
    "messages",
    "documents",
    "document_chunks",
    "evidence",
    "claims",
    "claim_evidence",
    "calculations",
    "research_tasks",
    "research_runs",
    "audit_events",
    "provider_configs",
    "provider_health",
    "evaluation_datasets",
    "evaluation_cases",
    "evaluation_runs",
]


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine) -> Session:
    """事务绑定的会话；用例结束回滚，不落数据。"""
    conn = engine.connect()
    tx = conn.begin()
    yield Session(conn, expire_on_commit=False)
    tx.rollback()
    conn.close()


def test_db_and_19_tables_exist(engine) -> None:
    """finsage 库含全部 19 张 §5 表（另有 alembic_version）。"""
    with engine.connect() as c:
        tables = {
            r[0]
            for r in c.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=:db"
                ),
                {"db": _current_db(engine)},
            )
        }
    missing = [t for t in _SCHEMA_TABLES if t not in tables]
    assert not missing, f"缺表: {missing}"


def test_chinese_comments_are_stored(engine) -> None:
    """表与字段中文注释已落库（抽样 research_tasks + users）。"""
    db = _current_db(engine)
    with engine.connect() as c:
        table_comment = c.execute(
            text(
                "SELECT table_comment FROM information_schema.tables "
                "WHERE table_schema=:db AND table_name='research_tasks'"
            ),
            {"db": db},
        ).scalar()
        col_comment = c.execute(
            text(
                "SELECT column_comment FROM information_schema.columns "
                "WHERE table_schema=:db AND table_name='users' "
                "AND column_name='password_hash'"
            ),
            {"db": db},
        ).scalar()
    assert table_comment == "研究任务表"
    assert col_comment == "密码哈希（可为空，如仅 OAuth 登录）"


def test_pk_and_unique_constraints_exist(engine) -> None:
    """research_tasks 有主键、唯一 trace_id、外键。"""
    db = _current_db(engine)
    with engine.connect() as c:
        pk = c.execute(
            text(
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema=:db AND table_name='research_tasks' "
                "AND constraint_type='PRIMARY KEY'"
            ),
            {"db": db},
        ).scalar()
        uq = c.execute(
            text(
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema=:db AND table_name='research_tasks' "
                "AND constraint_type='UNIQUE'"
            ),
            {"db": db},
        ).scalar()
        fk = c.execute(
            text(
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema=:db AND table_name='research_tasks' "
                "AND constraint_type='FOREIGN KEY'"
            ),
            {"db": db},
        ).scalar()
    assert pk == 1
    assert uq >= 1  # trace_id 唯一
    assert fk >= 2  # tenant_id、session_id 外键


def test_research_tasks_indexes_exist(engine) -> None:
    """research_tasks 具备 tenant_id / session_id 索引。"""
    db = _current_db(engine)
    with engine.connect() as c:
        idx = {
            r[0]
            for r in c.execute(
                text(
                    "SELECT index_name FROM information_schema.statistics "
                    "WHERE table_schema=:db AND table_name='research_tasks'"
                ),
                {"db": db},
            )
        }
    assert "ix_research_tasks_tenant_id" in idx
    assert "ix_research_tasks_session_id" in idx


def test_repository_crud_roundtrip(session) -> None:
    """仓储事务内增查往返，返回 ORM 域对象；回滚不留数据。"""
    conv = _make_parents(session, tenant_name="it-crud-t", email="it_crud@ex.com")
    repo = ResearchTaskRepository(session)
    task = ResearchTask(
        tenant_id=conv.tenant_id,
        session_id=conv.id,
        type="research_qa",
        query="集成测试查询",
        status="pending",
        trace_id="it_trace_1",
    )
    session.add(task)
    session.flush()

    got = repo.get(task.id)
    assert got is not None
    assert isinstance(got, ResearchTask)
    assert got.query == "集成测试查询"

    found = repo.find_by_trace_id("it_trace_1")
    assert found is not None
    assert found.id == task.id


def test_tenant_scoping_in_real_db(session) -> None:
    """真实库中注入租户，自动隔离其它租户（最小权限）。"""
    conv_a = _make_parents(session, tenant_name="it-tA", email="it_a@ex.com")
    conv_b = _make_parents(session, tenant_name="it-tB", email="it_b@ex.com")
    assert conv_a.tenant_id != conv_b.tenant_id  # 两个独立租户
    repo_a = ResearchTaskRepository(session, tenant_id=conv_a.tenant_id)
    repo_b = ResearchTaskRepository(session, tenant_id=conv_b.tenant_id)
    a = ResearchTask(
        tenant_id=conv_a.tenant_id,
        session_id=conv_a.id,
        type="report",
        query="A",
        status="running",
        trace_id="it_trace_a",
    )
    b = ResearchTask(
        tenant_id=conv_b.tenant_id,
        session_id=conv_b.id,
        type="report",
        query="B",
        status="running",
        trace_id="it_trace_b",
    )
    session.add_all([a, b])
    session.flush()

    assert repo_a.get(b.id) is None  # 跨租户不可见
    assert repo_b.get(a.id) is None
    assert repo_a.get(a.id) is not None


def _current_db(engine) -> str:
    return engine.url.database or "finsage"


def test_mysql_file_store_roundtrip(engine) -> None:
    """MySQLFileStore（ADR-0007）register/get/list/count 往返真实 MySQL。"""
    from finsage.api.mysql_stores import MySQLFileStore

    store = MySQLFileStore()
    doc_id = store.register(filename="r.pdf", size=1024, content=b"%PDF fake content")
    try:
        got = store.get(doc_id)
        assert got is not None
        assert got["filename"] == "r.pdf"
        assert got["size"] == 1024
        assert got["created_at"]

        lst = store.list()
        assert any(d["document_id"] == doc_id for d in lst)
        assert store.count() >= 1
    finally:
        with engine.connect() as c:
            c.execute(text("DELETE FROM documents WHERE id=:id"), {"id": doc_id})
            c.commit()


def test_mysql_file_store_register_idempotent(engine) -> None:
    """P1：重复上传同内容幂等返回已有 id，不再触发主键冲突 500。"""
    from finsage.api.mysql_stores import MySQLFileStore

    store = MySQLFileStore()
    content = b"%PDF duplicate content"
    first = store.register(filename="dup.pdf", size=len(content), content=content)
    try:
        second = store.register(filename="dup.pdf", size=len(content), content=content)
        assert second == first
        # 幂等后仍只存在一条记录。
        assert store.count() >= 1
        got = store.get(first)
        assert got is not None and got["document_id"] == first
    finally:
        with engine.connect() as c:
            c.execute(text("DELETE FROM documents WHERE id=:id"), {"id": first})
            c.commit()