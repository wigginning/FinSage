"""ADR-0016 checkpointer 工厂单测。

覆盖路由：memory → InMemorySaver；未知后端 → ValueError；mysql/redis 未装包 →
RuntimeError（诚实失败，不静默回退）。
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from finsage.settings import Settings
from finsage.workflows.checkpoint import build_checkpointer


def test_memory_backend_returns_in_memory_saver():
    cp = build_checkpointer(Settings(checkpoint_backend="memory"))
    assert isinstance(cp, InMemorySaver)


def test_unknown_backend_raises_value_error():
    with pytest.raises(ValueError):
        build_checkpointer(Settings(checkpoint_backend="postgres"))


def test_mysql_backend_missing_package_raises_runtime_error():
    # langgraph-checkpoint-mysql 未安装 -> 诚实抛错，不静默回退。
    with pytest.raises(RuntimeError):
        build_checkpointer(Settings(checkpoint_backend="mysql"))


def test_redis_backend_missing_package_raises_runtime_error():
    with pytest.raises(RuntimeError):
        build_checkpointer(Settings(checkpoint_backend="redis"))
