"""tenant-scoped documents.sha256 uniqueness (P1: 重复上传同内容 500)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 原 sha256 全局唯一 → 租户内唯一，跨租户上传相同内容互不冲突。
    op.execute("ALTER TABLE documents DROP INDEX uq_documents_sha256")
    op.execute(
        "ALTER TABLE documents "
        "ADD CONSTRAINT uq_documents_tenant_sha256 UNIQUE (tenant_id, sha256)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP INDEX uq_documents_tenant_sha256")
    op.execute("ALTER TABLE documents ADD CONSTRAINT uq_documents_sha256 UNIQUE (sha256)")
