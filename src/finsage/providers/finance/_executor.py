"""Bounded executor for blocking provider / SDK calls (tech-debt fix).

Problem
-------
``asyncio.wait_for(asyncio.to_thread(fn), timeout)`` cannot truly cancel the
worker thread: on timeout the asyncio future is cancelled, but the thread keeps
running ``fn`` to completion in the **default** (unbounded) executor, then the
result is discarded. Under load, timed-out calls pile up threads.

Same applies to ``BaseProvider._call``, which wraps ``asyncio.to_thread(...)``
in ``wait_for`` — a timeout there also orphans a thread.

Mitigation
----------
Two bounded pools, both capping the blast radius:

* :func:`run_blocking` runs blocking work on a **process-wide** bounded
  ``ThreadPoolExecutor`` (used explicitly by provider health probes via
  ``BaseProvider._run_blocking``).
* :func:`install_bounded_default_executor` installs a **per-loop** bounded
  executor as the running event loop's default executor, so *every*
  ``asyncio.to_thread`` in the process (providers' ``_call``, auth, memory,
  companies) is bounded too. The per-loop pool is loop-scoped: when the loop
  closes it is shut down, which is correct and does not touch the process-wide
  singleton.

True cancellation of a blocking C-extension SDK call (akshare/pytdx/efinance)
is not feasible without cooperative checks; the bounded pools bound the blast
radius instead of growing without limit.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from finsage.exceptions import ProviderTimeoutError

logger = logging.getLogger(__name__)

# Bound concurrent blocking SDK calls. Provider probes/timeouts and the steady
# stream of to_thread I/O are capped here so a hung SDK call cannot exhaust
# process threads.
_MAX_WORKERS = 16

# Process-wide singleton used by run_blocking() (provider health probes). It must
# outlive any individual event loop, so it is never installed as a loop's default
# executor.
_global_executor: ThreadPoolExecutor | None = None
_global_executor_lock = threading.Lock()

# Per-loop bounded executors installed as the loop's default executor. Keyed by
# the loop with a weak ref so we don't pin loops in memory; each is shut down
# when its loop closes (the intended lifecycle).
_loop_executors: weakref.WeakKeyDictionary[Any, ThreadPoolExecutor] = (
    weakref.WeakKeyDictionary()
)


def get_provider_executor() -> ThreadPoolExecutor:
    """Return the shared process-wide executor, creating it once on first use."""
    global _global_executor  # noqa: PLW0603 - module-level singleton, lazy
    if _global_executor is None:
        with _global_executor_lock:
            if _global_executor is None:
                _global_executor = ThreadPoolExecutor(
                    max_workers=_MAX_WORKERS, thread_name_prefix="finsage-provider"
                )
    return _global_executor


def install_bounded_default_executor(loop: asyncio.AbstractEventLoop) -> None:
    """Install a per-loop bounded executor as the loop's default (best-effort).

    Covers every ``asyncio.to_thread`` in the process for the loop's lifetime.
    The pool is loop-scoped (cached via weak ref); when the loop closes it is
    shut down, which is correct and does not affect the process-wide singleton.

    Guarded: the API is deprecated on 3.12+ and removed on 3.14, so its absence
    must not break app startup.
    """
    executor = _loop_executors.get(loop)
    if executor is None:
        executor = ThreadPoolExecutor(
            max_workers=_MAX_WORKERS, thread_name_prefix="finsage-loop"
        )
        _loop_executors[loop] = executor
    try:
        loop.set_default_executor(executor)
    except (AttributeError, NotImplementedError):  # pragma: no cover - future py
        logger.warning(
            "bounded_default_executor_unsupported",
            extra={"extra": {"loop": type(loop).__name__}},
        )


async def run_blocking(fn: Callable[[], Any], *, timeout: float | None = None) -> Any:
    """Run blocking ``fn`` on the process-wide bounded pool with a timeout.

    Raises :class:`ProviderTimeoutError` on timeout so callers' failover logic
    behaves correctly. The worker thread is *not* forcibly cancelled — it runs
    to completion in the bounded pool; the pool caps how many such orphans
    exist at once.
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(get_provider_executor(), fn)
    if timeout is None:
        return await fut
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except TimeoutError as exc:
        logger.warning(
            "blocking_call_timed_out_orphan_thread_may_persist",
            extra={"extra": {"pool": "finsage-provider"}},
        )
        raise ProviderTimeoutError("blocking provider call timed out") from exc


__all__ = [
    "get_provider_executor",
    "install_bounded_default_executor",
    "run_blocking",
]
