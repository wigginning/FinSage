"""对话域模型：messages（规格 §5.7）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Text

from finsage.persistence.base import Base, DateTime3, IdMixin, utcnow


class Message(IdMixin, Base):
    """消息（§5.7）。"""

    __tablename__ = "messages"
    __table_args__ = {"comment": "会话消息表"}

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID（外键，索引）",
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="角色：user/assistant/system"
    )
    content: Mapped[str] = mapped_column(
        Text(length=2**32 - 1), nullable=False, comment="消息内容（LONGTEXT）"
    )
    structured_answer_json: Mapped[Any | None] = mapped_column(
        JSON, nullable=True, comment="结构化回答（JSON，预留）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime3, default=utcnow, nullable=False, comment="创建时间（UTC）"
    )
