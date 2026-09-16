"""职责：Provider 健康度追踪与熔断容错（T304/T305/T303 工程骨架）。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from finsage.exceptions import FinSageError, ProviderError
from finsage.observability.logger import io_point

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """§10.3 熔断器。默认 failure_threshold=5 / open_interval_seconds=60 /
    half_open_probe=1（工程默认，不伪装数据源性能结论）。"""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        open_interval_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.open_interval_seconds = open_interval_seconds
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        opened = self._opened_at.get(key)
        if opened is None:
            return False
        return (time.monotonic() - opened) <= self.open_interval_seconds

    def snapshot(self, key: str) -> dict:
        opened = self._opened_at.get(key)
        return {
            "state": "open" if self.is_open(key) else "closed",
            "failure_count": self._failures.get(key, 0),
            "opened_at": opened or 0.0,
        }

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._opened_at.pop(key, None)

    def record_failure(self, key: str) -> None:
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self.failure_threshold:
            self._opened_at.setdefault(key, time.monotonic())

    @io_point("provider", "circuit_guard")
    async def guard(self, key: str, coro: Any) -> Any:
        """执行受保护调用；熔断开启立即抛 ProviderError（不可重试）。"""
        if self.is_open(key):
            raise ProviderError(f"circuit open: {key}", retryable=False) from None
        try:
            result = await coro
        except ProviderError as exc:
            if exc.retryable:
                self.record_failure(key)
            raise
        self.record_success(key)
        return result


async def retry(
    coro_fn: Any,
    *,
    retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 2.0,
) -> Any:
    """对可重试 ProviderError 指数退避重试；不可重试错误立即抛出。"""
    attempt = 0
    while True:
        try:
            return await coro_fn()
        except FinSageError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            await asyncio.sleep(delay)
            attempt += 1


def health_payload(
    *,
    capability: str,
    ok: bool,
    provider_name: str,
) -> bool:
    """记录一次调用成败的健康信号（provider_health 表写入由调用方接仓储完成）。"""
    logger.info(
        "provider.health",
        extra={"extra": {"provider": provider_name, "capability": capability, "ok": ok}},
    )
    return ok


__all__ = ["CircuitBreaker", "retry", "health_payload"]