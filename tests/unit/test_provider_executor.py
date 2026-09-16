"""Tests for the bounded provider executor (wait_for/to_thread thread-leak fix)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from finsage.exceptions import ProviderTimeoutError
from finsage.providers.finance._executor import (
    get_provider_executor,
    install_bounded_default_executor,
    run_blocking,
)


def _slow() -> str:
    time.sleep(0.3)
    return "done"


def _fast() -> str:
    return "ok"


async def test_run_blocking_returns_value() -> None:
    assert await run_blocking(_fast) == "ok"


async def test_run_blocking_raises_provider_timeout_on_slow() -> None:
    with pytest.raises(ProviderTimeoutError):
        await run_blocking(_slow, timeout=0.05)


async def test_run_blocking_no_timeout_completes() -> None:
    assert await run_blocking(_slow, timeout=1.0) == "done"


def test_get_provider_executor_is_singleton() -> None:
    assert get_provider_executor() is get_provider_executor()


def test_install_bounded_default_executor_sets_pool() -> None:
    loop = asyncio.new_event_loop()
    try:
        install_bounded_default_executor(loop)
        # 默认 executor 应被替换为有界池（不再是默认无界池）。
        assert loop._default_executor is not None
        assert loop._default_executor._max_workers == 16
        # 不应污染进程级单例（否则会随 loop 关闭被误关）。
        assert loop._default_executor is not get_provider_executor()
    finally:
        loop.close()


async def test_bounded_pool_caps_concurrent_threads() -> None:
    """同时发起超过池上限的阻塞调用，验证不会无限扩张（池大小固定）。"""
    ex = get_provider_executor()
    max_seen = 0
    lock = threading.Lock()

    def _track() -> None:
        nonlocal max_seen
        with lock:
            max_seen = max(max_seen, threading.active_count())
        time.sleep(0.1)

    tasks = [asyncio.create_task(run_blocking(_track)) for _ in range(ex._max_workers * 2)]
    await asyncio.gather(*tasks)
    # 活跃线程数不应显著超过池上限（含主线程/守护线程的合理余量）。
    assert max_seen <= ex._max_workers + 8
