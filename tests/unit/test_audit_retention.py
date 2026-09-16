"""P2 审计保留策略：AuditEventRepository.purge 清理测试（内存 SQLite）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finsage.persistence import base as pbase
from finsage.persistence.models.governance import AuditEvent, audit_retention_days
from finsage.persistence.repositories.governance import AuditEventRepository


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    pbase.Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _add_event(session: Session, created_at: datetime, *, tenant_id: str = "t1") -> AuditEvent:
    ev = AuditEvent(
        tenant_id=tenant_id,
        trace_id="tr-x",
        actor="agent",
        status="success",
        created_at=created_at,
    )
    session.add(ev)
    session.flush()
    return ev


def test_retention_default_days():
    assert audit_retention_days() == 90


def test_purge_before_removes_old_keeps_recent():
    session = _make_session()
    now = datetime.now()
    old = _add_event(session, now - timedelta(days=200))
    recent = _add_event(session, now - timedelta(days=1))
    session.commit()

    repo = AuditEventRepository(session)
    deleted = repo.purge_before(now - timedelta(days=90))
    session.commit()

    assert deleted == 1  # 只删旧事件
    assert repo.get(old.id) is None
    assert repo.get(recent.id) is not None
    session.close()


def test_purge_older_than_days():
    session = _make_session()
    now = datetime.now()
    _add_event(session, now - timedelta(days=120))
    _add_event(session, now - timedelta(days=10))
    session.commit()

    repo = AuditEventRepository(session)
    deleted = repo.purge_older_than_days(30)
    session.commit()

    assert deleted == 1  # 只清 30 天前的
    session.close()
