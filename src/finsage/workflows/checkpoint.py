"""LangGraph checkpointer 工厂（ADR-0016）。

按 ``checkpoint_backend`` 路由到持久化后端（MySQL/Redis）或内存 ``InMemorySaver``。
MySQL/Redis 后端**惰性导入**：未安装对应可选包时工厂仍可用（默认 memory），
仅当显式选择某后端且包缺失时才抛 ``RuntimeError``（诚实失败，不静默回退）。
"""
from __future__ import annotations

from typing import Any

from finsage.settings import Settings

__all__ = ["build_checkpointer"]


def build_checkpointer(settings: Settings | None = None) -> Any:
    """构建 LangGraph checkpointer（ADR-0016）。

    - ``memory``（默认）→ ``InMemorySaver``；
    - ``mysql`` → ``MySQLSaver.from_conn_string(db_url)``（惰性导入）；
    - ``redis`` → ``RedisSaver.from_conn_string(redis_url)``（惰性导入）；
    - 其它 → ``ValueError``。
    """
    s = settings or Settings()
    backend = s.checkpoint_backend

    if backend == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    if backend == "mysql":
        try:
            from langgraph.checkpoint.mysql import MySQLSaver
        except ImportError as exc:
            raise RuntimeError(
                "checkpoint_backend=mysql 需要安装 langgraph-checkpoint-mysql"
            ) from exc
        return MySQLSaver.from_conn_string(s.db_url)

    if backend == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver
        except ImportError as exc:
            raise RuntimeError(
                "checkpoint_backend=redis 需要安装 langgraph-checkpoint-redis"
            ) from exc
        return RedisSaver.from_conn_string(s.redis_url)

    raise ValueError(f"未知 checkpoint_backend: {backend!r}")
