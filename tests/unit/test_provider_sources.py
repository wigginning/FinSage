"""C-10 新增 Provider 契约测试：TencentQuoteProvider / TushareProvider。

- Tencent：用 httpx.MockTransport 拦截 HTTP 请求，验证契约五个方法 + 解析 + 错误映射，
  不依赖真实网络（单元测试不发外部请求，合规）。
- Tushare：token 缺失干净失败；注入 mock SDK 让 pro_api 可用，验证契约返回 + 错误映射。
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from finsage.exceptions import ProviderBadResponseError
from finsage.providers.finance import (
    SinaQuoteProvider,
    TencentQuoteProvider,
    TushareProvider,
)
from finsage.providers.finance.sina import (
    _cn_request_code as _sina_cn_request_code,
)
from finsage.providers.finance.tencent import _cn_request_code

# 模拟腾讯行情真实返回体（与 C-10 冒烟校准一致：平安银行 11.41）。
_PAYLOAD = (
    'v_sz000001="1~平安银行~000001~11.41~11.40~11.41~'
    "1119277~127580960000~0.01~0.09~11.40~11.41~11.42~11.45~11.32~"
    "11.41~11.32~26.22~691850786~0~0~--~0~0~0~0~0~0~0~0~0~0~0~"
    "11.46~11.32~11.41~0.09~ FP ~8.05~--~0~0~0~0~0~0~0~0~0~0~0~--~"
    "0.09~1.17~0.00~0~0~-~--~0~0~0~0~0~0~0~0~0~0~0~"
    '20260823153000"'  # noqa: E501 - 模拟外部响应体，非代码行
)


def _tencent_fields() -> list[str]:
    return _PAYLOAD.split("=", 1)[1][1:-1].split("~")


def _tencent_provider() -> TencentQuoteProvider:
    return TencentQuoteProvider()


# ---- Tencent 契约 ----

async def test_tencent_get_quote(monkeypatch) -> None:
    p = _tencent_provider()

    async def _fake_fetch(code: str) -> list[str]:  # noqa: ARG001
        return _tencent_fields()

    monkeypatch.setattr(p, "_fetch_quote", _fake_fetch)
    quote = await p.get_quote("000001", "CN.SZ")
    assert quote.symbol == "000001"
    assert quote.market == "CN.SZ"
    assert quote.name == "平安银行"
    assert quote.price == Decimal("11.41")
    assert quote.currency == "CNY"
    assert quote.source == "tencent"


async def test_tencent_get_quote_parses_code_and_handles_sh() -> None:
    assert _cn_request_code("600519", "CN") == "sh600519"


async def test_tencent_financials_unsupported() -> None:
    p = _tencent_provider()
    assert await p.get_financials("000001", "CN", "") == []


async def test_tencent_news_unsupported() -> None:
    p = _tencent_provider()
    assert await p.get_news("000001", "CN") == []


async def test_tencent_company_profile_minimal(monkeypatch) -> None:
    p = _tencent_provider()

    async def _fake_fetch(code: str) -> list[str]:  # noqa: ARG001
        return _tencent_fields()

    monkeypatch.setattr(p, "_fetch_quote", _fake_fetch)
    profile = await p.get_company_profile("000001", "CN")
    assert profile.name == "平安银行"
    assert profile.currency == "CNY"
    assert profile.country == "CN"


async def test_tencent_short_payload_raises(monkeypatch) -> None:
    p = _tencent_provider()

    async def _short(code: str) -> list[str]:  # noqa: ARG001
        return ["a", "b", "c"]

    monkeypatch.setattr(p, "_fetch_quote", _short)
    with pytest.raises(ProviderBadResponseError):
        await p.get_quote("000001", "CN")


async def test_tencent_health_down_on_failure(monkeypatch) -> None:
    p = _tencent_provider()

    async def _boom(symbol: str, market: str) -> object:  # noqa: ARG001
        raise ConnectionError("network down")

    monkeypatch.setattr(p, "get_quote", _boom)
    health = await p.health_check()
    assert health.status == "down"


# ---- Tushare 契约 ----

def _mock_pro_api() -> MagicMock:
    pro = MagicMock()
    quote_frame = MagicMock()
    quote_frame.to_dict.return_value = [
        {"ts_code": "000001.SZ", "name": "平安银行", "price": "11.41", "pre_close": "11.40"}
    ]
    pro.ts_realtime_quote.return_value = quote_frame

    fin_frame = MagicMock()
    fin_frame.to_dict.return_value = [
        {"ts_code": "000001.SZ", "revenue": "100", "n_income": "20", "total_assets": "500"}
    ]
    pro.fina_indicator.return_value = fin_frame

    basic_frame = MagicMock()
    basic_frame.to_dict.return_value = [
        {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行"}
    ]
    pro.stock_basic.return_value = basic_frame
    return pro


def test_tushare_requires_token():
    p = TushareProvider(token=None)
    with pytest.raises(ProviderBadResponseError):
        p._require_token()


async def test_tushare_get_quote_with_token_and_sdk(monkeypatch) -> None:
    p = TushareProvider(token="fake-token")
    mock_sdk = MagicMock()
    mock_sdk.pro_api.return_value = _mock_pro_api()
    monkeypatch.setattr(
        "finsage.providers.finance.tushare.TushareProvider._load_sdk",
        staticmethod(lambda: mock_sdk),
    )
    quote = await p.get_quote("000001", "CN.SZ")
    assert quote.symbol == "000001"
    assert quote.price == Decimal("11.41")
    assert quote.currency == "CNY"
    assert quote.source == "tushare"


async def test_tushare_health_down_without_token() -> None:
    p = TushareProvider(token=None)
    health = await p.health_check()
    assert health.status == "down"


async def test_tushare_get_news_unsupported() -> None:
    p = TushareProvider(token="t")
    assert await p.get_news("000001", "CN") == []


async def test_tushare_cn_code() -> None:
    p = TushareProvider(token="t")
    assert p._cn_code("sh600519") == "600519"


# ---- Sina 契约 ----

# 模拟新浪行情真实返回体（与 C-10 冒烟校准一致：平安银行 11.410）。
_SINA_PAYLOAD = (
    'var hq_str_sz000001="平安银行,11.360,11.400,11.410,11.460,11.320,11.410,'
    "11.420,86912763,990112066.410,35814,11.410,344300,11.400,205600,11.390,"
    "179000,11.380,125100,11.370,42800,11.420,388992,11.430,260200,11.440,"
    '445700,11.450,661600,11.460,2026-08-21,16:29:00,00";'
)


def _sina_fields() -> list[str]:
    return _SINA_PAYLOAD.split('"')[1].split(",")


def _sina_provider() -> SinaQuoteProvider:
    return SinaQuoteProvider()


async def test_sina_get_quote(monkeypatch) -> None:
    p = _sina_provider()

    async def _fake_fetch(code: str) -> list[str]:  # noqa: ARG001
        return _sina_fields()

    monkeypatch.setattr(p, "_fetch_quote", _fake_fetch)
    quote = await p.get_quote("000001", "CN.SZ")
    assert quote.symbol == "000001"
    assert quote.market == "CN.SZ"
    assert quote.name == "平安银行"
    assert quote.price == Decimal("11.41")
    assert quote.currency == "CNY"
    assert quote.source == "sina"


async def test_sina_cn_request_code() -> None:
    assert _sina_cn_request_code("600519", "CN") == "sh600519"
    assert _sina_cn_request_code("000001", "CN.SH") == "sh000001"


async def test_sina_financials_news_unsupported(monkeypatch) -> None:
    p = _sina_provider()

    async def _fake_fetch(code: str) -> list[str]:  # noqa: ARG001
        return _sina_fields()

    monkeypatch.setattr(p, "_fetch_quote", _fake_fetch)
    assert await p.get_financials("000001", "CN", "") == []
    assert await p.get_news("000001", "CN") == []


async def test_sina_company_profile_minimal(monkeypatch) -> None:
    p = _sina_provider()

    async def _fake_fetch(code: str) -> list[str]:  # noqa: ARG001
        return _sina_fields()

    monkeypatch.setattr(p, "_fetch_quote", _fake_fetch)
    profile = await p.get_company_profile("000001", "CN")
    assert profile.name == "平安银行"
    assert profile.currency == "CNY"
    assert profile.country == "CN"


async def test_sina_short_or_empty_price_raises(monkeypatch) -> None:
    p = _sina_provider()

    async def _short(code: str) -> list[str]:  # noqa: ARG001
        return ["a", "b", "c"]

    async def _empty_price(code: str) -> list[str]:  # noqa: ARG001
        return ["平安银行", "11.360", "11.400", "", "11.460", "11.320"]

    monkeypatch.setattr(p, "_fetch_quote", _short)
    with pytest.raises(ProviderBadResponseError):
        await p.get_quote("000001", "CN")
    monkeypatch.setattr(p, "_fetch_quote", _empty_price)
    with pytest.raises(ProviderBadResponseError):
        await p.get_quote("000001", "CN")


async def test_sina_health_down_on_failure(monkeypatch) -> None:
    p = _sina_provider()

    async def _boom(symbol: str, market: str) -> object:  # noqa: ARG001
        raise ConnectionError("network down")

    monkeypatch.setattr(p, "get_quote", _boom)
    health = await p.health_check()
    assert health.status == "down"


def test_yfinance_uses_finsage_bad_response_error():
    """yfinance 模块不应再定义遮蔽性 ProviderBadResponseError（普通 Exception），
    否则会逃逸 failover/retry/熔断。应为 finsage.exceptions 的真实子类。"""
    import finsage.providers.finance.yfinance_provider as mod
    from finsage.exceptions import FinSageError

    cls = mod.ProviderBadResponseError
    assert issubclass(cls, FinSageError)
    assert cls.code is not None  # 携带 FIN 错误码