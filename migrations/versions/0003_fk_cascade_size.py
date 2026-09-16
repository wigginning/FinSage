"""add FK cascade + align documents.size type (P2: 外键级联/类型漂移)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (table, fk_name, referenced_table, column) 列表。
# 约束名遵循 persistence/base.py 的 NAMING_CONVENTION：fk_<table>_<column>_<referred>。
_CASCADE_FKS = [
    # document_chunks.document_id -> documents.id（删文档级联删片段）
    ("document_chunks", "fk_document_chunks_document_id_documents", "documents", "document_id"),
    # evidence.document_id -> documents.id
    ("evidence", "fk_evidence_document_id_documents", "documents", "document_id"),
    # evidence.chunk_id -> document_chunks.id
    ("evidence", "fk_evidence_chunk_id_document_chunks", "document_chunks", "chunk_id"),
    # claim_evidence.claim_id -> claims.id
    ("claim_evidence", "fk_claim_evidence_claim_id_claims", "claims", "claim_id"),
    # claim_evidence.evidence_id -> evidence.id
    ("claim_evidence", "fk_claim_evidence_evidence_id_evidence", "evidence", "evidence_id"),
    # claims.research_run_id -> research_runs.id
    ("claims", "fk_claims_research_run_id_research_runs", "research_runs", "research_run_id"),
    # calculations.research_run_id -> research_runs.id
    (
        "calculations",
        "fk_calculations_research_run_id_research_runs",
        "research_runs",
        "research_run_id",
    ),
    # messages.session_id -> sessions.id
    ("messages", "fk_messages_session_id_sessions", "sessions", "session_id"),
]


def upgrade() -> None:
    op.execute("SET FOREIGN_KEY_CHECKS=0")
    # 逐表替换外键为 ON DELETE CASCADE（孤儿数据风险，P2）。
    for table, fk_name, ref_table, column in _CASCADE_FKS:
        op.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {fk_name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {fk_name} "
            f"FOREIGN KEY ({column}) REFERENCES {ref_table} (id) "
            "ON DELETE CASCADE"
        )
    # 对齐 documents.size 类型漂移（模型 BigInteger vs 迁移 BIGINT）。
    op.execute(
        "ALTER TABLE documents "
        "MODIFY COLUMN size BIGINT NOT NULL COMMENT '文件大小（字节，工程补全 ADR-0007）'"
    )
    op.execute("SET FOREIGN_KEY_CHECKS=1")


def downgrade() -> None:
    op.execute("SET FOREIGN_KEY_CHECKS=0")
    for table, fk_name, ref_table, column in _CASCADE_FKS:
        op.execute(f"ALTER TABLE {table} DROP FOREIGN KEY {fk_name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {fk_name} "
            f"FOREIGN KEY ({column}) REFERENCES {ref_table} (id)"
        )
    op.execute(
        "ALTER TABLE documents "
        "MODIFY COLUMN size INTEGER NOT NULL COMMENT '文件大小（字节，工程补全 ADR-0007）'"
    )
    op.execute("SET FOREIGN_KEY_CHECKS=1")
