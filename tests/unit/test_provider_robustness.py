"""Provider 与运行时健壮性回归测试（审计 §2.5 / §2.6 / §2.7 / §2.4）。

冻结四类此前缺失的边界：
- 后处理段异常必须映射为 ProviderError，才能进 failover 链（不被穿透）；
- NaN / Infinity 不得进入 Quote.price 污染下游确定性计算；
- Baostock 全局会话必须串行化；
- checkpoint thread_id 必须随调用下发（ADR-0016 才能真正续跑）。
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finsage.api.schemas import ChatRequest, ResearchRequest
from finsage.exceptions import ProviderBadResponseError, ProviderError
from finsage.providers.finance.akshare import AKShareProvider
from finsage.providers.finance.baostock import BaoStockProvider
from finsage.providers.finance.base import BaseProvider
from finsage.providers.finance.efinance import EFinanceProvider
from finsage.providers.finance.sina import SinaQuoteProvider
from finsage.providers.finance.tencent import TencentQuoteProvider
from finsage.providers.finance.tushare import TushareProvider

# ---------------------------------------------------------------------------
# 后处理段异常保护（审计 §2.5）
# ---------------------------------------------------------------------------


def test_guard_parse_maps_unexpected_exception_to_provider_error() -> None:
    """非 ProviderError 一律转 ProviderBadResponseError，进入 failover 链。"""
    provider = BaseProvider()

    def boom() -> None:
        raise AttributeError("'NoneType' object has no attribute 'iterrows'")

    with pytest.raises(ProviderBadResponseError):
        provider._guard_parse("quote", boom)


def test_guard_parse_passes_through_provider_error() -> None:
    """已是 ProviderError 的不重复包装，保留原有错误码语义。"""
    provider = BaseProvider()

    def raise_provider_error() -> None:
        raise ProviderBadResponseError("missing price")

    with pytest.raises(ProviderBadResponseError) as exc:
        provider._guard_parse("quote", raise_provider_error)
    assert "missing price" in str(exc.value)


def _patch_call(provider: BaseProvider, result: object) -> None:
    """把 ``_call`` 换成直接返回 result 的桩，并关闭未使用的协程避免警告。"""

    async def _fake_call(operation: str, coro: object) -> object:
        close = getattr(coro, "close", None)
        if callable(close):
            close()  # 未执行的 to_thread 协程，显式关闭
        return result

    provider._call = _fake_call  # type: ignore[method-assign]


def test_akshare_quote_bad_frame_type_fails_as_provider_error() -> None:
    """frame 结构非预期（None）不再抛裸 AttributeError 打穿 failover 链。"""
    provider = AKShareProvider()
    fake_sdk = type("Sdk", (), {"stock_individual_info_em": staticmethod(lambda **kw: None)})()
    provider._load_sdk = lambda: fake_sdk  # type: ignore[method-assign]
    _patch_call(provider, None)  # SDK 返回非 DataFrame
    with pytest.raises(ProviderError):
        asyncio.run(provider.get_quote("600519", "CN"))


def test_efinance_quote_bad_row_fails_as_provider_error() -> None:
    provider = EFinanceProvider()
    _patch_call(provider, None)  # row 为 None -> row.get 抛 AttributeError
    with pytest.raises(ProviderError):
        asyncio.run(provider.get_quote("600519", "CN"))


def test_tushare_quote_bad_payload_fails_as_provider_error() -> None:
    provider = TushareProvider(token="dummy")  # type: ignore[call-arg]
    _patch_call(provider, object())  # 既无 to_dict 也不可迭代
    with pytest.raises(ProviderError):
        asyncio.run(provider.get_quote("600519", "CN"))


# ---------------------------------------------------------------------------
# NaN / Infinity 防护（审计 §2.6）
# ---------------------------------------------------------------------------


_NON_FINITE: list[object] = [
    "nan",
    "NaN",
    "inf",
    "-inf",
    "Infinity",
    float("nan"),
    float("inf"),
    float("-inf"),
]


@pytest.mark.parametrize("bad", _NON_FINITE)
def test_tencent_to_decimal_rejects_non_finite(bad: object) -> None:
    from finsage.providers.finance.tencent import _to_decimal

    assert _to_decimal(bad) is None


@pytest.mark.parametrize("bad", ["nan", "inf", "Infinity", float("nan"), float("-inf")])
def test_sina_to_decimal_rejects_non_finite(bad: object) -> None:
    from finsage.providers.finance.sina import _to_decimal

    assert _to_decimal(bad) is None


@pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-Infinity"])
def test_baostock_to_decimal_rejects_non_finite(bad: str) -> None:
    """此前只挡 nan/NaN，inf/Infinity 可穿过并污染下游计算。"""
    assert BaoStockProvider._to_decimal(bad) is None


@pytest.mark.parametrize("good", ["11.41", "0", "-3.5", 12])
def test_to_decimal_still_accepts_valid_numbers(good: object) -> None:
    from finsage.providers.finance.tencent import _to_decimal as tencent_decimal

    assert tencent_decimal(good) == Decimal(str(good))


def test_providers_module_import_guard() -> None:
    """常量/类未被误删（akshare 辅助函数曾因缩进错误截断类定义）。"""
    assert hasattr(AKShareProvider, "get_quote")
    assert hasattr(AKShareProvider, "get_financials")
    assert TencentQuoteProvider.name == "tencent"
    assert SinaQuoteProvider.name == "sina"


# ---------------------------------------------------------------------------
# Baostock 全局会话串行化（审计 §2.7）
# ---------------------------------------------------------------------------


def test_baostock_query_serializes_global_session(monkeypatch) -> None:
    """并发调用必须串行：任一方 logout 不得关掉另一方正在用的会话。

    Baostock 的 login/logout 是进程级全局会话，不加锁时并发请求会互相踩踏。
    """
    import sys
    import threading
    import time

    events: list[str] = []
    ok = type("R", (), {"error_code": "0", "error_msg": ""})()
    # ``_query`` 内部是 ``import baostock as bs``，必须注入 sys.modules 才生效。
    monkeypatch.setitem(
        sys.modules,
        "baostock",
        type(
            "FakeBs",
            (),
            {
                "login": staticmethod(lambda: ok),
                "logout": staticmethod(lambda: events.append("logout")),
            },
        )(),
    )

    provider = BaoStockProvider()
    lock = threading.Lock()
    active = {"n": 0, "max": 0}

    def slow_query(_bs: object) -> object:
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        # 制造稳定的重叠窗口：无锁时三个线程必会同时处于活动态。
        time.sleep(0.05)
        with lock:
            active["n"] -= 1
        return type(
            "RS",
            (),
            {"error_code": "0", "error_msg": "", "fields": ["a"], "data": [["1"]]},
        )()

    async def one() -> list[dict[str, str]]:
        return await asyncio.to_thread(provider._query, "op", slow_query)

    async def run() -> None:
        await asyncio.gather(one(), one(), one())

    asyncio.run(run())
    # 串行锁保证任一时刻只有一个会话处于活动状态（无锁时这里会是 3）。
    assert active["max"] == 1
    assert events.count("logout") == 3


# ---------------------------------------------------------------------------
# 输入校验边界（审计 §2.6）
# ---------------------------------------------------------------------------


def test_research_request_rejects_overlong_query() -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(query="x" * 4001)


def test_research_request_accepts_query_at_limit() -> None:
    assert ResearchRequest(query="x" * 4000).query.endswith("xxxx")


def test_chat_request_rejects_overlong_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001)


@pytest.mark.parametrize("market", ["CN", "US", "HK", "GLOBAL"])
def test_research_request_accepts_known_markets(market: str) -> None:
    assert ResearchRequest(query="营收多少", market=market).market == market  # type: ignore[arg-type]


def test_research_request_rejects_unknown_market() -> None:
    """非法市场不得一路透传到 Provider 路由后才失败。"""
    with pytest.raises(ValidationError):
        ResearchRequest(query="营收多少", market="XX")  # type: ignore[arg-type]
