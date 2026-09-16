"""add filename/size to documents (ADR-0007)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents "
        "ADD COLUMN filename VARCHAR(500) NOT NULL COMMENT '文件名（上传元数据，工程补全 ADR-0007）' "
        "AFTER title"
    )
    op.execute(
        "ALTER TABLE documents "
        "ADD COLUMN size BIGINT NOT NULL COMMENT '文件大小（字节，工程补全 ADR-0007）' "
        "AFTER filename"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN size")
    op.execute("ALTER TABLE documents DROP COLUMN filename")
