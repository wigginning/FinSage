"""evaluation tenant_id 收紧为 NOT NULL（ADR-0022：FinEval API 强制租户隔离）

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-29

ADR-0019 §5 先加列并为历史数据回填默认租户（0005，列暂可空）。本迁移在 ADR-0022
FinEval API 落地时把三张评估表的 ``tenant_id`` 收紧为 NOT NULL，使写入强制归属租户、
读取强制按租户隔离（消除越权读隐患）。

步骤：确保默认租户存在 → 回填剩余 NULL → 改列 NOT NULL。幂等，可重复执行。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_TABLES = ("evaluation_datasets", "evaluation_cases", "evaluation_runs")


def _default_tenant_name() -> str:
    """默认占位租户名（来自配置，单引号已转义以防 SQL 拼接问题）。"""
    from finsage.settings import get_settings

    return get_settings().default_tenant.replace("'", "''")


def upgrade() -> None:
    name = _default_tenant_name()
    # 1) 确保默认占位租户存在（INSERT IGNORE 避免重复）。
    op.execute(
        "INSERT IGNORE INTO tenants (id, name, status, created_at, updated_at) "
        f"VALUES (UUID(), '{name}', 'active', NOW(3), NOW(3))"
    )
    default_tenant_id = (
        f"(SELECT id FROM tenants WHERE name = '{name}' LIMIT 1)"
    )
    for table in _TABLES:
        # 2) 回填：任何残留 NULL 归入默认租户（保证下一步 NOT NULL 不失败）。
        op.execute(
            f"UPDATE {table} SET tenant_id = {default_tenant_id} WHERE tenant_id IS NULL"
        )
        # 3) 收紧为 NOT NULL（保留既有索引/外键）。
        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.String(36),
            nullable=False,
        )


def downgrade() -> None:
    # 回退为可空（不删除默认租户，避免误删其它域使用的租户）。
    for table in _TABLES:
        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.String(36),
            nullable=True,
        )
