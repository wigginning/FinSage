"""对话域仓储：messages（规格 §5.7）。"""

from __future__ import annotations

from finsage.persistence.models.chat import Message
from finsage.persistence.repositories.base import FilteredRepository


class MessageRepository(FilteredRepository):
    """消息仓储。白名单筛选：session_id / role。"""

    model = Message
    allow_filters = frozenset({"session_id", "role"})

    def list_for_session(self, session_id: str, *, limit: int = 200, offset: int = 0) -> list:
        """按会话**升序**取消息（域对象列表）——"从头翻阅会话"语义，用于分页浏览。

        注意：升序 + LIMIT 取到的是**最旧** N 条，不适合做上下文窗口；
        上下文窗口请用 ``list_recent_for_session``（ADR-0023）。
        """
        stmt = (
            self.filter(session_id=session_id)
            .order_by(Message.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_recent_for_session(self, session_id: str, *, limit: int = 20) -> list:
        """取会话**最近** N 条消息，返回时间正序（ADR-0023 上下文窗口语义）。

        实现：倒序 + LIMIT 拿到最新 N 条（走 (session_id, created_at) 索引，
        不全表扫），再在内存中反转回时间正序供 LLM 消费。
        """
        stmt = (
            self.filter(session_id=session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list(self._session.execute(stmt).scalars().all())
        rows.reverse()
        return rows
