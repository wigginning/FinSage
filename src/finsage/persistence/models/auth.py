"""认证/租户域模型：users、tenants、user_tenants、sessions（规格 §5.3–5.6）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from finsage.persistence.base import Base, DateTime3, IdMixin, TimestampMixin, utcnow


class User(IdMixin, TimestampMixin, Base):
    """用户（§5.3）。"""

    __tablename__ = "users"
    __table_args__ = {"comment": "用户表"}

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, comment="邮箱（唯一）"
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, comment="显示名")
    password_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="密码哈希（可为空，如仅 OAuth 登录）"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="状态：active/disabled")


class Tenant(IdMixin, TimestampMixin, Base):
    """租户（§5.4）。"""

    __tablename__ = "tenants"
    __table_args__ = {"comment": "租户表"}

    name: Mapped[str] = mapped_column(
        String(120), unique=True, nullable=False, comment="租户名（唯一）"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="状态：active/disabled")


class UserTenant(Base):
    """用户-租户关联（§5.5，复合主键）。"""

    __tablename__ = "user_tenants"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenants_user_tenant"),
        {"comment": "用户与租户的关联表"},
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True, nullable=False, comment="用户ID"
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), primary_key=True, nullable=False, comment="租户ID"
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, comment="在该租户内的角色")
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )


class Session(IdMixin, TimestampMixin, Base):
    """会话（§5.6）。"""

    __tablename__ = "sessions"
    __table_args__ = {"comment": "会话表"}

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="租户ID（外键，索引）",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="用户ID（外键，索引）",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="会话标题")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="会话摘要")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="状态：active/completed/archived"
    )
