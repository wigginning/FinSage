"""P1 任务管理器：SSE 订阅者清理 + 并发背压测试（离线）。"""

from __future__ import annotations

import asyncio
import contextlib

from finsage.api.tasks import TaskHandle, TaskManager


async def test_subscriber_removed_after_stream_closes():
    """P1：流断开后订阅队列应从 _subscribers 移除，避免无界泄漏。"""
    handle = TaskHandle(task_id="t1", trace_id="tr1")

    # 创建生成器并推进到阻塞点（等待队列），然后关闭触发 finally 清理。
    gen = handle.subscribe()
    task = asyncio.create_task(_collect(gen))
    await asyncio.sleep(0.01)
    assert handle._subscribers  # 已注册
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # 取消后生成器 finally 清理队列。
    assert handle._subscribers == []


async def _collect(agen):
    async for _ev in agen:
        pass


async def test_subscriber_cleanup_on_full_consume():
    """正常消费完（含结束哨兵）后队列也被移除。"""
    handle = TaskHandle(task_id="t2", trace_id="tr2", status="completed")

    async def drain():
        async for _ev in handle.subscribe():
            pass

    await drain()
    assert handle._subscribers == []


async def test_task_duration_recorded_on_completion():
    """P2：任务完成后应记录 started_at/finished_at，可算耗时（历史页"耗时"列）。"""
    async def quick_run(h):
        await asyncio.sleep(0.01)

    mgr = TaskManager()
    h = await mgr.submit("research", trace_id="tr1", run=quick_run)
    await asyncio.sleep(0.05)
    assert h.status == "completed"
    assert h.started_at is not None
    assert h.finished_at is not None
    dur = h.duration_seconds()
    assert dur is not None and dur >= 0
    # 未完成的任务无耗时。
    h2 = TaskHandle(task_id="t2", trace_id="tr2")
    assert h2.duration_seconds() is None


async def test_concurrency_limit_backpressure():
    """P1：并发上限内执行，超限任务排队等待（背压）。"""
    release = asyncio.Event()
    active = 0
    max_active = 0

    async def slow_run(h):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await release.wait()
        active -= 1

    mgr = TaskManager(max_concurrent=2)
    handles = []
    for i in range(5):
        h = await mgr.submit("generic", trace_id=f"tr{i}", run=slow_run)
        handles.append(h)
        await asyncio.sleep(0.01)

    # 排队中应只有 2 个在运行（active<=2），其余等待 semaphore。
    assert max_active <= 2
    # 全部仍处于 queued/running（未被执行完成）。
    await asyncio.sleep(0.05)
    assert max_active <= 2
    release.set()
    await asyncio.sleep(0.1)
    # 全部最终执行完成。
    assert all(h.status in {"completed", "failed"} for h in handles)
