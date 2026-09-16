"""任务管理与 SSE 事件总线（m08，T804/T805，§7.3/§26.9）。

设计：
- ``TaskHandle``：单个任务的运行态（task_id / trace_id / status / progress / result）+
  replay 缓冲 + 订阅队列（迟到订阅可回放已发生事件）；
- ``TaskManager.submit``：入队并后台执行可注入的 ``run``（工作流 runner），
  由 manager 负责状态机（queued→running→completed/failed），并规范产出
  workflow.started / task.completed / task.failed / error 等 §26.9 事件；
- ``subscribe``：将指定任务的事件流作为异步生成器产出（供 /stream SSE）。

不依赖真实 DB / 工作流：生产实例注入 m06 图执行器，测试注入替身。
"""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from finsage.api.schemas import SSEEvent
from finsage.exceptions import ErrorCode, FinSageError
from finsage.observability.logger import get_logger, io_point
from finsage.observability.trace import uuid_str

logger = get_logger(__name__)

# §26.9 事件类型集合（FROZEN）。
WORKFLOW_STARTED = "workflow.started"
WORKFLOW_STAGE = "workflow.stage"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
TASK_ABORTED = "task.aborted"
ERROR_EVENT = "error"

# _Run: 工作流执行回调（由 manager 调用并接管状态机）。
_Run = Callable[["TaskHandle"], Awaitable[None]]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TaskHandle:
    """单个任务的运行态与事件来源。"""

    task_id: str
    trace_id: str
    kind: str = "generic"
    status: str = "queued"  # queued/running/completed/failed/aborted
    progress: float = 0.0
    result: Any = None
    error_code: str | None = None
    query: str | None = None
    company: str | None = None
    ticker: str | None = None
    market: str | None = None
    tenant_id: str | None = None  # P0 权限：任务归属租户（IDOR/隔离用）
    created_at: str = field(default_factory=_iso_now)
    # P2 历史页"耗时"：记录实际起止时间，供前端计算耗时（不再恒 "—"）。
    started_at: str | None = None
    finished_at: str | None = None
    _buffer: deque[SSEEvent] = field(default_factory=deque)
    _subscribers: list[asyncio.Queue[SSEEvent | None]] = field(default_factory=list)

    def duration_seconds(self) -> float | None:
        """任务耗时（秒）；未完成/缺少时间则返回 None。"""
        if not self.started_at or not self.finished_at:
            return None
        try:
            from datetime import datetime

            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.finished_at)
            return (end - start).total_seconds()
        except ValueError:
            return None

    def emit(self, type_: str, data: dict[str, Any] | None = None) -> SSEEvent:
        """产出一条 §26.9 事件：入 replay 缓冲并扇出给订阅者。"""
        event = SSEEvent(
            event_id=uuid_str(),
            trace_id=self.trace_id,
            timestamp=_iso_now(),
            type=type_,
            data=data or {},
        )
        self._buffer.append(event)
        for q in self._subscribers:
            q.put_nowait(event)
        return event

    def set_progress(self, value: float) -> None:
        """更新进度（0..1，越界自动夹紧）。"""
        self.progress = max(0.0, min(1.0, float(value)))

    def subscribe(self) -> AsyncIterator[SSEEvent]:
        """为一次流式连接创建一个订阅队列并回放既有事件。

        P1：连接断开（生成器结束/异常）时自动从 ``_subscribers`` 移除队列，
        避免订阅者无界累积导致内存泄漏。
        """
        queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()
        self._subscribers.append(queue)
        ordered = list(self._buffer)
        # 快照 connect 时刻状态：若任务已终结，回放后直接结束，避免等待一个
        # 已被消耗的终止哨兵导致流永不关闭（迟到订阅竞态）。
        terminal = self.status in {"completed", "failed", "aborted"}

        async def generator() -> AsyncIterator[SSEEvent]:
            try:
                for ev in ordered:  # 先回放已发生事件
                    yield ev
                if terminal:
                    return
                while True:
                    item = await queue.get()
                    if item is None:  # 结束哨兵
                        return
                    yield item
            finally:
                # 连接关闭：移除本订阅队列，释放引用（P1 内存泄漏修复）。
                with contextlib.suppress(ValueError):
                    self._subscribers.remove(queue)

        return generator()


class TaskManager:
    """内存任务管理器：提交、状态机、事件总线。

    P1 并发控制：``max_concurrent`` 限制同时运行的后台任务数（背压）——
    达到上限时新提交排队等待，避免无上限 create_task 导致资源耗尽。
    """

    def __init__(self, max_concurrent: int = 32) -> None:
        self._tasks: dict[str, TaskHandle] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))

    def get(self, task_id: str) -> TaskHandle | None:
        """按 task_id 取任务；不存在返回 None。"""
        return self._tasks.get(task_id)

    def count(self, *, status: str | None = None, kind: str | None = None) -> int:
        """筛选后的任务总数（用于分页）。"""
        return sum(
            1
            for t in self._tasks.values()
            if (status is None or t.status == status) and (kind is None or t.kind == kind)
        )

    def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskHandle]:
        """按创建时间倒序分页列出任务（支持 status/kind 筛选）。"""
        items = [
            t
            for t in self._tasks.values()
            if (status is None or t.status == status) and (kind is None or t.kind == kind)
        ]
        items.sort(key=lambda t: t.created_at, reverse=True)
        return items[offset : offset + max(0, limit)]

    @io_point("api", "task_submit")
    async def submit(
        self,
        kind: str,
        *,
        trace_id: str,
        run: _Run,
        query: str | None = None,
        company: str | None = None,
        ticker: str | None = None,
        market: str | None = None,
        tenant_id: str | None = None,
    ) -> TaskHandle:
        """创建任务并入队后台执行。``run`` 为工作流 runner，达 handle。

        ``query``/``company``/``ticker``/``market`` 透传自 research 请求，供列表视图展示
        主题与公司（§7.3 TaskSummary 扩展；chat 类任务不传，列表对应字段为 null）。
        ``tenant_id`` 透传请求身份租户，供 IDOR 归属校验与检索隔离。
        """
        handle = TaskHandle(
            task_id=uuid_str(),
            trace_id=trace_id,
            kind=kind,
            query=query,
            company=company,
            ticker=ticker,
            market=market,
            tenant_id=tenant_id,
        )
        async with self._lock:
            self._tasks[handle.task_id] = handle

        async def _guarded() -> None:
            # P1 背压：并发上限内执行，否则排队等待；被取消/正常结束后释放。
            try:
                async with self._semaphore:
                    await self._execute(handle, run)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_guarded())
        self._running[handle.task_id] = task
        task.add_done_callback(
            lambda _t: self._running.pop(handle.task_id, None)  # 释放运行态引用
        )
        return handle

    async def abort(self, task_id: str) -> TaskHandle | None:
        """中止任务：取消后台执行并等待其收尾（``_execute`` 捕获 CancelledError
        置 aborted 并发 task.aborted）。

        幂等：任务不存在返回 None；已终结（completed/failed/aborted）原样返回，不重复发事件。
        """
        handle = self._tasks.get(task_id)
        if handle is None:
            return None
        if handle.status in {"completed", "failed", "aborted"}:
            return handle
        task = self._running.get(task_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task  # _execute 已捕获并置 aborted / 发 task.aborted
        return handle

    async def _execute(self, handle: TaskHandle, run: _Run) -> None:
        """状态机执行体：queued→running→completed/failed。"""
        handle.status = "running"
        handle.started_at = _iso_now()  # P2：记录实际开始时间（耗时统计）
        handle.emit(WORKFLOW_STARTED, {"task_id": handle.task_id, "kind": handle.kind})
        try:
            await run(handle)
            handle.status = "completed"
            handle.progress = 1.0
            handle.finished_at = _iso_now()
            handle.emit(TASK_COMPLETED, {"task_id": handle.task_id, "kind": handle.kind})
        except FinSageError as exc:
            handle.status = "failed"
            handle.error_code = exc.code.value
            handle.finished_at = _iso_now()
            handle.emit(
                TASK_ABORTED if exc.code is ErrorCode.WORKFLOW_CANCELLED else TASK_FAILED,
                {"task_id": handle.task_id, "code": handle.error_code},
            )
            handle.emit(ERROR_EVENT, {"code": handle.error_code, "retryable": exc.retryable})
        except asyncio.CancelledError:
            handle.status = "aborted"
            handle.finished_at = _iso_now()
            handle.emit(TASK_ABORTED, {"task_id": handle.task_id})
            raise
        except Exception as exc:  # noqa: BLE001 —— 未归类异常统一折成 INTERNAL_ERROR
            # P1 后台异常可见性：静默吞掉使失败不可诊断（实测 L5 FIN-6001），
            # 此处记录结构化日志（含 trace_id/异常类型，不含堆栈敏感字段）。
            logger.error(
                "task.unhandled_error",
                extra={
                    "extra": {
                        "task_id": handle.task_id,
                        "trace_id": handle.trace_id,
                        "kind": handle.kind,
                        "error": type(exc).__name__,
                    }
                },
            )
            handle.status = "failed"
            handle.error_code = ErrorCode.INTERNAL_ERROR.value
            handle.emit(TASK_FAILED, {"task_id": handle.task_id, "code": handle.error_code})
            handle.emit(ERROR_EVENT, {"code": handle.error_code, "retryable": False})
        finally:
            await self._close(handle)

    async def _close(self, handle: TaskHandle) -> None:
        """向所有订阅者发送结束哨兵（None）：由 END 终止流。"""
        for q in handle._subscribers:
            q.put_nowait(None)

    async def stream(self, task_id: str) -> AsyncIterator[SSEEvent]:
        """产出指定任务的 SSE 事件流；任务不存在则结束。"""
        handle = self.get(task_id)
        if handle is None:
            return
        async for ev in handle.subscribe():
            yield ev


__all__ = [
    "TaskManager",
    "TaskHandle",
    "WORKFLOW_STARTED",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_ABORTED",
    "ERROR_EVENT",
]