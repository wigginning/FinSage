"""evaluation tenant_id（ADR-0019 §5：评估域租户隔离先加列 + 回填）

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29

为 ``evaluation_datasets`` / ``evaluation_cases`` / ``evaluation_runs`` 增加
``tenant_id``（可空、索引、外键到 ``tenants.id``），并把历史数据回填到默认租户
（``settings.default_tenant``，默认 ``__default__``）。

列**暂可空**：评估当前仅脚本离线跑（无 HTTP 身份可解析租户），强制隔离待 ADR-0022
FinEval API 落地时一并接线，届时收紧为 NOT NULL。故本次迁移不破坏既有写入路径。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_TABLES = ("evaluation_datasets", "evaluation_cases", "evaluation_runs")


def _default_tenant_name() -> str:
    """默认占位租户名（来自配置，单引号已转义以防 SQL 拼接问题）。"""
    from finsage.settings import get_settings

    return get_settings().default_tenant.replace("'", "''")


def upgrade() -> None:
    name = _default_tenant_name()
    # 1) 确保默认占位租户存在：tenants.name 上有唯一索引，重复时 INSERT IGNORE 直接跳过。
    op.execute(
        "INSERT IGNORE INTO tenants (id, name, status, created_at, updated_at) "
        f"VALUES (UUID(), '{name}', 'active', NOW(3), NOW(3))"
    )
    for table in _TABLES:
        # 2) 加列（可空，兼容既有写入路径）。
        op.add_column(table, sa.Column("tenant_id", sa.String(36), nullable=True))
        # 3) 回填：无租户归属的历史数据归入默认租户。
        op.execute(
            f"UPDATE {table} SET tenant_id = "
            f"(SELECT id FROM tenants WHERE name = '{name}' LIMIT 1) "
            "WHERE tenant_id IS NULL"
        )
        # 4) 索引 + 外键（命名对齐 persistence/base.py 的 NAMING_CONVENTION）。
        op.execute(f"CREATE INDEX ix_{table}_tenant_id ON {table} (tenant_id)")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_tenant_id_tenants "
            "FOREIGN KEY (tenant_id) REFERENCES tenants (id)"
        )


def downgrade() -> None:
    # 反向只移除本次新增对象；不删除默认租户（避免误删其它域仍在使用的租户）。
    for table in reversed(_TABLES):
        op.execute(f"ALTER TABLE {table} DROP FOREIGN KEY fk_{table}_tenant_id_tenants")
        op.execute(f"ALTER TABLE {table} DROP INDEX ix_{table}_tenant_id")
        op.drop_column(table, "tenant_id")
