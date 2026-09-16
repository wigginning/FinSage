"""MySQL 持久化仓储（启用 ``enable_persistence`` 时替换内存 Store）。

当前实现：
- 审计轨迹 MySQL 落地（``MySQLAuditStore``，每次工作流运行都会写审计）；
- 文档上传元数据 MySQL 落地（``MySQLFileStore``，ADR-0007，替换内存 ``FileStore``）；
- ``EvidenceStore`` 暂保留内存实现（见 P2-C.2 后续）。

前置条件：先 ``alembic upgrade head`` 并保证 ``FIN_DB_URL`` 可达。
接口对齐内存版 Store（``add``/``get``/``list``/``count``）。
"""
from __future__ import annotations

import hashlib
from typing import Any

from finsage.persistence.db import session_scope
from finsage.persistence.models.auth import Tenant
from finsage.persistence.models.governance import AuditEvent
from finsage.persistence.models.rag import Document
from finsage.settings import get_settings


# 单租户/无租户场景的占位 tenant（与既有仓储缺省一致）；名从 settings.default_tenant
# 读取，不再硬编码字面量。
def _default_tenant_name() -> str:
    return get_settings().default_tenant


def _ensure_default_tenant(session) -> str:
    """确保默认租户存在并返回其 id（documents.tenant_id 有 FK 到 tenants.id）。"""
    name = _default_tenant_name()
    tenant = session.query(Tenant).filter(Tenant.name == name).first()
    if tenant is None:
        tenant = Tenant(name=name, status="active")
        session.add(tenant)
        session.flush()
    return tenant.id


def _resolve_tenant(session, tenant_id: str | None) -> str:
    """把请求租户映射为真实 tenants.id；缺省占位走既有默认租户。

    有请求租户时尝试按 id 定位（不存在则回退默认占位）；无请求租户时返回
    默认租户占位（与既有行为一致，P0 权限由上层 IDOR 校验兜底）。
    """
    if tenant_id:
        row = session.query(Tenant).filter(Tenant.id == tenant_id).first()
        if row is not None:
            return tenant_id
    return _ensure_default_tenant(session)


def _document_id(tenant_id: str, content_hash: str) -> str:
    """按 (租户, 内容) 寻址的文档 ID：同租户同内容稳定，跨租户互不冲突。

    P1：原实现用 ``sha256(content)[:36]`` 作主键，重复上传同内容触发主键冲突 500；
    改为租户参与寻址后，同租户重复上传幂等返回已有 id，跨租户上传相同内容互不干扰。
    """
    return hashlib.sha256(f"{tenant_id}:{content_hash}".encode()).hexdigest()[:36]


class MySQLAuditStore:
    """审计轨迹 MySQL 仓储：接口对齐内存 ``AuditStore``。"""

    def add(self, trace_id: str, event: dict[str, Any], *, tenant_id: str = "") -> None:
        with session_scope() as session:
            resolved = _resolve_tenant(session, tenant_id or None)
            row = AuditEvent(
                tenant_id=resolved,
                trace_id=trace_id,
                stage=event.get("stage"),
                status=event.get("status", "success"),
                error_code=event.get("error_code"),
                output_json=event,
                actor=event.get("actor") or "api",
            )
            session.add(row)

    def get(self, trace_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with session_scope() as session:
            q = session.query(AuditEvent).filter(AuditEvent.trace_id == trace_id)
            if tenant_id:
                q = q.filter(AuditEvent.tenant_id == tenant_id)
            rows = q.order_by(AuditEvent.created_at.asc()).all()
            return [r.output_json for r in rows if r.output_json is not None]

    def owner_tenant(self, trace_id: str) -> str:
        """取审计链路归属租户（接口对齐内存 ``AuditStore``；未记录返回空串）。"""
        with session_scope() as session:
            row = (
                session.query(AuditEvent)
                .filter(AuditEvent.trace_id == trace_id)
                .order_by(AuditEvent.created_at.asc())
                .first()
            )
            return row.tenant_id or "" if row is not None else ""


class MySQLFileStore:
    """文档上传元数据 MySQL 仓储（ADR-0007）：接口对齐内存 ``FileStore``。

    ``register`` 写入 ``documents`` 表（title=filename，filename=filename，size=size，
    source_type='upload'，status='ingested'，authority_tier=0，sha256=内容哈希）。
    """

    max_bytes: int = 5 * 1024 * 1024  # 与内存 FileStore 对齐（§7.5 文档大小上限）

    def register(
        self, *, filename: str, size: int, content: bytes, tenant_id: str = ""
    ) -> str:
        content_hash = hashlib.sha256(content).hexdigest()
        with session_scope() as session:
            resolved_tenant = _resolve_tenant(session, tenant_id or None)
            document_id = _document_id(resolved_tenant, content_hash)
            # P1 幂等：同租户重复上传同内容返回已有 id，不再触发主键冲突 500。
            if session.get(Document, document_id) is not None:
                return document_id
            row = Document(
                id=document_id,
                tenant_id=resolved_tenant,
                title=filename,
                filename=filename,
                size=size,
                source_type="upload",
                sha256=content_hash,
                authority_tier=0,
                status="ingested",
            )
            session.add(row)
        return document_id

    def get(
        self, document_id: str, *, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.get(Document, document_id)
            if row is None:
                return None
            if tenant_id and row.tenant_id != tenant_id:
                return None
            return self._to_dict(row)

    def list(
        self, *, limit: int = 50, offset: int = 0, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        with session_scope() as session:
            q = session.query(Document)
            if tenant_id:
                q = q.filter(Document.tenant_id == tenant_id)
            rows = q.order_by(Document.created_at.desc()).limit(limit).offset(offset).all()
            return [self._to_dict(r) for r in rows]

    def count(self, *, tenant_id: str | None = None) -> int:
        with session_scope() as session:
            q = session.query(Document)
            if tenant_id:
                q = q.filter(Document.tenant_id == tenant_id)
            return q.count()

    @staticmethod
    def _to_dict(row: Document) -> dict[str, Any]:
        return {
            "document_id": row.id,
            "filename": row.filename,
            "size": row.size,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "tenant_id": row.tenant_id,
        }


__all__ = ["MySQLAuditStore", "MySQLFileStore"]
