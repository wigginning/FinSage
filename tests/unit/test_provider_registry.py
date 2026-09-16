"""T302/T304/T305/T311 —— Registry 路由、Failover、熔断、重试（§10）。"""

from __future__ import annotations

import pytest

from finsage.exceptions import ProviderError, ProviderTimeoutError
from finsage.providers.finance import CircuitBreaker, ProviderRegistry
from finsage.providers.finance.resilience import retry


class _DummyProvider:
    """带失败开关的伪 Provider，用于验证 Registry 编排。"""

    def __init__(self, *, name: str = "dummy", fail: bool = False):
        self.name = name
        self.fail = fail
        self.calls = 0

    async def get_quote(self, symbol: str, market: str):
        self.calls += 1
        if self.fail:
            raise ProviderTimeoutError("boom")
        return {"provider": self.name, "symbol": symbol}


async def test_registry_routes_and_returns_primary():
    p1 = _DummyProvider(name="p1")
    p2 = _DummyProvider(name="p2")
    r = ProviderRegistry()
    r.register(p1, {"quote": ["CN"]})
    r.register(p2, {"quote": ["CN"]})

    out = await r.invoke(lambda p: p.get_quote("600519", "CN"), operation="quote", market="CN")
    assert out["provider"] == "p1"
    assert p1.calls == 1
    assert p2.calls == 0  # 主用命中，不触发备用


async def test_registry_failover_to_secondary():
    p1 = _DummyProvider(name="p1", fail=True)
    p2 = _DummyProvider(name="p2")
    r = ProviderRegistry()
    r.register(p1, {"quote": ["CN"]})
    r.register(p2, {"quote": ["CN"]})

    out = await r.invoke(lambda p: p.get_quote("600519", "CN"), operation="quote", market="CN")
    assert out["provider"] == "p2"
    assert p2.calls == 1


async def test_registry_no_provider_raises():
    from finsage.exceptions import MarketDataUnavailableError

    r = ProviderRegistry()
    with pytest.raises(MarketDataUnavailableError):
        await r.invoke(lambda p: p.get_quote("x", "XX"), operation="quote", market="XX")


async def test_registry_all_fail_raises_last_error():
    p1 = _DummyProvider(name="p1", fail=True)
    p2 = _DummyProvider(name="p2", fail=True)
    r = ProviderRegistry()
    r.register(p1, {"quote": ["CN"]})
    r.register(p2, {"quote": ["CN"]})

    with pytest.raises(ProviderError):
        await r.invoke(lambda p: p.get_quote("600519", "CN"), operation="quote", market="CN")


# ---- 优先级路由（对齐 daily_stock_analysis 的 priority 语义）----


async def test_registry_priority_orders_candidates():
    """priority 越小越优先：高优先源先被调用，低优先源仅作 failover 兜底。"""
    low = _DummyProvider(name="low")
    high = _DummyProvider(name="high")
    r = ProviderRegistry()
    r.register(low, {"quote": ["CN"]}, priority=90)
    r.register(high, {"quote": ["CN"]}, priority=0)

    out = await r.invoke(lambda p: p.get_quote("600519", "CN"), operation="quote", market="CN")
    assert out["provider"] == "high"
    assert high.calls == 1
    assert low.calls == 0


async def test_registry_priority_failover_to_lower_priority():
    """高优先源失败时，failover 到低优先源。"""
    high = _DummyProvider(name="high", fail=True)
    low = _DummyProvider(name="low")
    r = ProviderRegistry()
    r.register(high, {"quote": ["CN"]}, priority=0)
    r.register(low, {"quote": ["CN"]}, priority=90)

    out = await r.invoke(lambda p: p.get_quote("600519", "CN"), operation="quote", market="CN")
    assert out["provider"] == "low"
    assert low.calls == 1


async def test_registry_default_priority_is_100():
    """未显式指定 priority 时默认 100（低优先，注册顺序不再决定顺序）。"""
    a = _DummyProvider(name="a")
    b = _DummyProvider(name="b")
    r = ProviderRegistry()
    r.register(a, {"quote": ["CN"]})  # 默认 100
    r.register(b, {"quote": ["CN"]}, priority=0)

    out = await r.invoke(lambda p: p.get_quote("600519", "CN"), operation="quote", market="CN")
    assert out["provider"] == "b"  # 显式低值优先，而非注册顺序 a


# ---- CircuitBreaker ----


async def test_breaker_opens_after_threshold():
    b = CircuitBreaker(failure_threshold=3, open_interval_seconds=60.0)

    async def boom():
        raise ProviderTimeoutError("boom")

    for _ in range(3):
        with pytest.raises(ProviderError):
            await b.guard("q.cn", boom())

    assert b.snapshot("q.cn")["state"] == "open"
    with pytest.raises(ProviderError):
        await b.guard("q.cn", boom())


async def test_breaker_success_resets():
    b = CircuitBreaker(failure_threshold=5, open_interval_seconds=60.0)

    async def boom():
        raise ProviderTimeoutError("boom")

    # 一次失败：计数置 1，仍闭合，不熔断
    with pytest.raises(ProviderError):
        await b.guard("k", boom())
    assert b.snapshot("k")["failure_count"] == 1
    assert b.snapshot("k")["state"] == "closed"

    async def ok():
        return "ok"

    # 闭合态下一次成功即复位计数
    assert await b.guard("k", ok()) == "ok"
    assert b.snapshot("k")["failure_count"] == 0
    assert b.snapshot("k")["state"] == "closed"


def test_failover_key_includes_provider_name():
    """P1：熔断 key 应含 provider 名，避免单源故障熔断整条 failover 链。"""
    reg = ProviderRegistry()
    key = reg._failover_key("financials", "CN", _Named("yfinance"))
    assert key == "financials.CN.yfinance"
    # 不同 provider 的 key 应不同。
    other = reg._failover_key("financials", "CN", _Named("akshare"))
    assert other != key


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


# ---- Retry ----


async def test_retry_succeeds_after_failures():
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ProviderTimeoutError("retry me")
        return "recovered"

    assert await retry(flaky, retries=3, base_delay=0.0) == "recovered"
    assert attempts["n"] == 3


async def test_retry_exhausted_raises():
    async def always_fail():
        raise ProviderTimeoutError("nope")

    with pytest.raises(ProviderError):
        await retry(always_fail, retries=2, base_delay=0.0)


async def test_retry_non_retryable_immediately():
    async def bad():
        raise ProviderError("fatal", retryable=False)

    with pytest.raises(ProviderError):
        await retry(bad, retries=3, base_delay=0.0)