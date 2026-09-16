"""持久化基座（T101/T103 基础设施）。

- DeclarativeBase + 全局命名规范（保证 alembic 生成稳定的约束名）；
- ID 默认 CHAR(36) UUID（见 observability.trace.uuid_str）；
- 时间统一 DATETIME(3) 且存 UTC（naive UTC，MySQL DATETIME 不保存时区）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import MetaData, String
from sqlalchemy.dialects.mysql import DATETIME as MySQLDATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from finsage.observability.trace import uuid_str

# 命名规范：约束名形如 pk_users / fk_sessions_tenant_id_tenants / uq_xxx / ix_xxx。
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# DATETIME(3) —— 规格要求 DATETIME(3)（毫秒精度）；通用 sqlalchemy.DateTime 不支持 fsp，
# 故统一用 MySQL 方言 DATETIME(fsp=3)（架构冻结 = MySQL 8）。原样复用同一类型实例即可。
DateTime3 = MySQLDATETIME(fsp=3)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类；统一绑定命名规范。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """当前 UTC 时间（naive），契合计时字段存 DATETIME(3) UTC 的约定。"""
    return datetime.now(UTC).replace(tzinfo=None)


class IdMixin:
    """CHAR(36) UUID 主键。"""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)


class TimestampMixin:
    """created_at / updated_at（DATETIME(3) UTC）。"""

    created_at: Mapped[datetime] = mapped_column(DateTime3, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, onupdate=utcnow, nullable=False
    )
