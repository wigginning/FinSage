"""T302 Provider Registry（§9/§10 编排层）。

职责：
1. 注册 Provider 实例与能力（quote/financials/company_profile/news/health）；
2. 按市场/能力路由到 Primary Provider；
3. 支持 Failover（§10.2：Primary -> Secondary -> Tertiary -> Graceful Degradation），
   结合 CircuitBreaker/retry 编排。

规则：上层（MCP/Agent）只与 Registry 交互，绝不直接触及底层 SDK（AGENTS.md §4）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from finsage.exceptions import MarketDataUnavailableError, ProviderBadResponseError, ProviderError

from .resilience import CircuitBreaker, retry

logger = logging.getLogger(__name__)


class Capabilities(TypedDict, total=False):
    quote: list[str]  # 支持的市场，如 ["CN", "US"]
    financials: list[str]
    company_profile: list[str]
    news: list[str]


@dataclass
class _ProviderEntry:
    instance: Any
    name: str
    capabilities: Capabilities
    priority: int = 100  # 越小越优先（对齐 daily_stock_analysis 的 priority 语义）

    def supports(self, operation: str, market: str) -> bool:
        markets = cast(list[str] | None, self.capabilities.get(operation))
        return markets is not None and market in markets


class ProviderRegistry:
    """按市场/能力路由并编排 failover 的 Provider 注册表。"""

    def __init__(self) -> None:
        self._providers: dict[str, _ProviderEntry] = {}
        self.breaker = CircuitBreaker()

    def register(
        self,
        instance: Any,
        capabilities: Capabilities,
        *,
        priority: int = 100,
    ) -> None:
        """注册一个 Provider 实例及其能力声明。同名 Provider 重复注册则覆盖。

        ``priority`` 越小越优先（对齐 daily_stock_analysis 的 priority 语义）：
        可用/免费/无 token 的数据源给低值（高优先），需 token 或 SDK 未安装的
        不可用源给高值（低优先），使 failover 先走可用源。
        """
        name = getattr(instance, "name", type(instance).__name__)
        self._providers[name] = _ProviderEntry(
            instance=instance,
            name=name,
            capabilities=capabilities,
            priority=priority,
        )
        logger.info(
            "provider_registered",
            extra={"extra": {"name": name, "caps": capabilities, "priority": priority}},
        )

    def names(self) -> list[str]:
        return list(self._providers)

    def get(self, name: str) -> Any:
        entry = self._providers.get(name)
        return entry.instance if entry else None

    def _candidates(self, operation: str, market: str) -> list[Any]:
        """按能力过滤并按 priority 升序（高优先在前）返回候选 Provider。"""
        entries = [e for e in self._providers.values() if e.supports(operation, market)]
        entries.sort(key=lambda e: e.priority)
        return [e.instance for e in entries]

    def _failover_key(self, operation: str, market: str, provider: Any) -> str:
        # P1：熔断 key 需含 provider 名，否则单源故障会熔断整条 failover 链，
        # 使其它可用 Provider 也无法被尝试。
        name = getattr(provider, "name", type(provider).__name__)
        return f"{operation}.{market}.{name}"

    async def invoke(
        self,
        factory: Callable[[Any], Awaitable[Any]],
        *,
        operation: str,
        market: str,
        retries: int = 1,
    ) -> Any:
        """按候选 Provider 依次 failover 调用 `factory(provider)`。

        - 每个候选先经 CircuitBreaker.guard 保护，再按 retry 策略尝试；
        - 全部失败按最终错误向上抛（Graceful Degradation 语义由上层处理）。
        """
        candidates = self._candidates(operation, market)
        if not candidates:
            raise MarketDataUnavailableError(f"no provider for {operation}.{market}")

        last_error: Exception | None = None
        for provider in candidates:
            key = self._failover_key(operation, market, provider)
            try:
                # 绑定当前 provider（def 默认参数），避免 loop 变量闭包共享。
                def _partial(p=provider):  # noqa: ANN001
                    return factory(p)

                return await self.breaker.guard(key, retry(_partial, retries=retries))
            except ProviderError as exc:
                logger.warning(
                    "provider_failed",
                    extra={
                        "extra": {
                            "provider": getattr(provider, "name", type(provider).__name__),
                            "operation": operation,
                            "error_code": exc.code.value,
                        }
                    },
                )
                last_error = exc
                continue

        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderBadResponseError(f"all providers failed for {operation}.{market}")


__all__ = ["ProviderRegistry", "Capabilities"]