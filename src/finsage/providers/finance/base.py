"""T301 Provider Protocol 与基础 Provider（§9 Contract — FROZEN 接口）。

每个 Provider 只实现 FinancialDataProvider 接口，返回 Pydantic/domain 对象，
不泄露第三方 SDK 数据结构；捕 SDK 异常映射到 FIN 错误码；支持 timeout / health_check；
记录 provider name 与 retrieved_at；LLM 永不直接调 SDK（经 Provider Registry）。

本文件只定义契约与通用骨架，不落地任何具体数据源（见各 Provider 模块）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from finsage.exceptions import (
    NormalizationError,
    ProviderBadResponseError,
    ProviderError,
    ProviderTimeoutError,
)

from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote

logger = logging.getLogger(__name__)


@runtime_checkable
class FinancialDataProvider(Protocol):
    """§9.1 Financial Provider Interface（FROZEN）。"""

    name: str

    async def get_quote(self, symbol: str, market: str) -> Quote: ...
    async def get_financials(
        self, symbol: str, market: str, period: str
    ) -> list[FinancialMetric]: ...
    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile: ...
    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]: ...
    async def health_check(self) -> ProviderHealth: ...


class BaseProvider:
    """Provider 通用基类。

    `name` 与 `capability_prefix` 由子类声明；timeout 为工程默认值，
    不伪装为数据源性能结论（见 No-Guess 边界）。
    """

    name: str = ""
    capability_prefix: str = ""  # 如 "quote"/"financials"，用于 health capability 命名
    default_timeout: float = 10.0

    def __init__(self, *, timeout: float | None = None) -> None:
        self.timeout = timeout if timeout is not None else self.default_timeout

    def _capability(self, operation: str) -> str:
        """组合 capability 标识（如 `akshare.quote`），写 provider_health 用。"""
        prefix = f"{self.capability_prefix}." if self.capability_prefix else ""
        return f"{prefix}{operation}"

    def _utcnow(self) -> datetime:
        return datetime.now(UTC)

    async def _call(self, operation: str, coro: Any) -> Any:
        """在超时窗口内执行 SDK coroutine；超时抛 ProviderTimeoutError，
        其它 SDK 异常交由 `_map_sdk_error` 映射后统一抛出。"""
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout)
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"{self.name}.{operation} timed out") from exc
        except Exception as exc:  # noqa: BLE001 - SDK 异常统一映射
            raise self._map_sdk_error(operation, exc) from exc

    async def _run_blocking(self, fn: Any, *, timeout: float | None = None) -> Any:
        """Run a blocking SDK call on the bounded provider executor.

        Wraps :func:`finsage.providers.finance._executor.run_blocking` so
        provider subclasses can offload sync SDK work without leaking threads
        into the default (unbounded) executor on timeout. Defaults to
        ``self.timeout`` when not given.
        """
        from ._executor import run_blocking

        return await run_blocking(fn, timeout=timeout if timeout is not None else self.timeout)

    def _map_sdk_error(self, operation: str, exc: Exception) -> ProviderError:
        """SDK 异常默认映射：未识别类型按 ProviderBadResponseError（子类可覆盖）。"""
        return ProviderBadResponseError(f"{self.name}.{operation}: {type(exc).__name__}")

    def _guard_parse(self, operation: str, fn: Any) -> Any:
        """响应解析段（``_call`` 返回之后）的异常保护。

        审计 §2.5：``_call`` 之外的后处理若抛 AttributeError/KeyError 等裸异常，
        会直接穿透 Registry 的 failover 链（那里只捕获 ``ProviderError``），
        导致单源异常中断整条降级链。这里把非 ``ProviderError`` 统一映射为
        ``ProviderBadResponseError``，让解析失败也走正常的 failover。
        """
        try:
            return fn()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - 解析段异常统一映射
            logger.warning(
                "provider_parse_failed provider=%s operation=%s exc=%s",
                self.name,
                operation,
                type(exc).__name__,
            )
            raise ProviderBadResponseError(
                f"{self.name}.{operation}: parse failed ({type(exc).__name__})"
            ) from exc


def validate_financials(items: list[Any]) -> list[FinancialMetric]:
    """校验并归一化财务指标列表；任一非法抛 NormalizationError。"""
    result: list[FinancialMetric] = []
    for item in items:
        if not isinstance(item, FinancialMetric):
            try:
                item = FinancialMetric.model_validate(item)
            except Exception as exc:  # noqa: BLE001
                raise NormalizationError(f"invalid metric: {exc}") from exc
        result.append(item)
    return result


def ensure_symbol_market(symbol: str, market: str) -> None:
    """契约守卫：symbol/market 非空，为空抛 NormalizationError。"""
    if not symbol or not market:
        raise NormalizationError("symbol and market are required")


def utcnow() -> datetime:
    """统一取 UTC now，避免各 Provider 各自处理时区。"""
    return datetime.now(UTC)


__all__ = [
    "FinancialDataProvider",
    "BaseProvider",
    "validate_financials",
    "ensure_symbol_market",
    "utcnow",
]