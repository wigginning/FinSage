"""EFinanceProvider / PytdxProvider 契约测试（新增可用免费数据源）。

- EFinance：mock efinance SDK 的 get_realtime_quotes，验证契约五个方法 + 解析 + 错误映射，
  不依赖真实网络（单元测试不发外部请求，合规）。
- Pytdx：mock pytdx SDK 的 get_security_quotes / get_finance_info，验证契约 + 错误映射。
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from finsage.exceptions import ProviderBadResponseError
from finsage.providers.finance import EFinanceProvider, PytdxProvider

# ---- EFinance 契约 ----

def _efinance_frame() -> pd.DataFrame:
    """模拟 efinance get_realtime_quotes 返回（平安银行 000001，最新价 11.41）。"""
    return pd.DataFrame(
        [
            {
                "股票代码": "000001",
                "股票名称": "平安银行",
                "最新价": "11.41",
                "市盈率-动态": "5.2",
                "市净率": "0.8",
                "总市值": "2214.0",
                "换手率": "0.5",
            }
        ]
    )


def _efinance_provider(monkeypatch) -> EFinanceProvider:
    p = EFinanceProvider()
    sdk = MagicMock()
    sdk.stock.get_realtime_quotes.return_value = _efinance_frame()
    monkeypatch.setattr(
        "finsage.providers.finance.efinance.EFinanceProvider._load_sdk",
        staticmethod(lambda: sdk),
    )
    return p


async def test_efinance_get_quote(monkeypatch) -> None:
    p = _efinance_provider(monkeypatch)
    quote = await p.get_quote("000001", "CN.SZ")
    assert quote.symbol == "000001"
    assert quote.market == "CN.SZ"
    assert quote.name == "平安银行"
    assert quote.price == Decimal("11.41")
    assert quote.currency == "CNY"
    assert quote.source == "efinance"


async def test_efinance_get_financials(monkeypatch) -> None:
    p = _efinance_provider(monkeypatch)
    metrics = await p.get_financials("000001", "CN", "")
    by_metric = {m.metric: m for m in metrics}
    assert by_metric["pe"].value == Decimal("5.2")
    assert by_metric["pb"].value == Decimal("0.8")
    assert by_metric["market_cap"].value == Decimal("2214.0")
    assert by_metric["market_cap"].currency == "CNY"
    assert all(m.source == "efinance" for m in metrics)


async def test_efinance_get_company_profile(monkeypatch) -> None:
    p = _efinance_provider(monkeypatch)
    profile = await p.get_company_profile("000001", "CN")
    assert profile.name == "平安银行"
    assert profile.currency == "CNY"
    assert profile.country == "CN"


async def test_efinance_news_unsupported(monkeypatch) -> None:
    p = _efinance_provider(monkeypatch)
    assert await p.get_news("000001", "CN") == []


async def test_efinance_health_down_on_failure(monkeypatch) -> None:
    p = EFinanceProvider()

    def _boom() -> object:
        raise ConnectionError("network down")

    monkeypatch.setattr(p, "_sdk_probe", _boom)
    health = await p.health_check()
    assert health.status == "down"


async def test_efinance_missing_price_raises(monkeypatch) -> None:
    p = EFinanceProvider()
    sdk = MagicMock()
    sdk.stock.get_realtime_quotes.return_value = pd.DataFrame(
        [{"股票代码": "000001", "股票名称": "平安银行", "最新价": None}]
    )
    monkeypatch.setattr(
        "finsage.providers.finance.efinance.EFinanceProvider._load_sdk",
        staticmethod(lambda: sdk),
    )
    with pytest.raises(ProviderBadResponseError):
        await p.get_quote("000001", "CN")


# ---- Pytdx 契约 ----

def _pytdx_provider(monkeypatch) -> PytdxProvider:
    p = PytdxProvider(hosts=[("127.0.0.1", 7709)])
    api = MagicMock()
    api.get_security_quotes.return_value = [
        {"market": 0, "code": "000001", "name": "平安银行", "price": 11.41}
    ]
    api.get_finance_info.return_value = {
        "code": "000001",
        "name": "平安银行",
        "pe": 5.2,
        "pb": 0.8,
        "total_capital": 2214.0,
    }
    api.connect.return_value = True
    monkeypatch.setattr(
        "finsage.providers.finance.pytdx.PytdxProvider._load_sdk",
        staticmethod(lambda: api.__class__),
    )
    # 让 _connect 返回 mock api 实例
    monkeypatch.setattr(p, "_connect", lambda: api)
    return p


async def test_pytdx_get_quote(monkeypatch) -> None:
    p = _pytdx_provider(monkeypatch)
    quote = await p.get_quote("000001", "CN.SZ")
    assert quote.symbol == "000001"
    assert quote.market == "CN.SZ"
    assert quote.name == "平安银行"
    assert quote.price == Decimal("11.41")
    assert quote.currency == "CNY"
    assert quote.source == "pytdx"


async def test_pytdx_get_financials(monkeypatch) -> None:
    p = _pytdx_provider(monkeypatch)
    metrics = await p.get_financials("000001", "CN", "")
    by_metric = {m.metric: m for m in metrics}
    assert by_metric["pe"].value == Decimal("5.2")
    assert by_metric["pb"].value == Decimal("0.8")
    assert by_metric["market_cap"].value == Decimal("2214.0")
    assert all(m.source == "pytdx" for m in metrics)


async def test_pytdx_get_company_profile(monkeypatch) -> None:
    p = _pytdx_provider(monkeypatch)
    profile = await p.get_company_profile("000001", "CN")
    assert profile.name == "平安银行"
    assert profile.currency == "CNY"
    assert profile.country == "CN"


async def test_pytdx_news_unsupported(monkeypatch) -> None:
    p = _pytdx_provider(monkeypatch)
    assert await p.get_news("000001", "CN") == []


async def test_pytdx_health_down_on_failure(monkeypatch) -> None:
    p = PytdxProvider(hosts=[("127.0.0.1", 7709)])

    def _boom() -> object:
        raise ConnectionError("network down")

    monkeypatch.setattr(p, "_sdk_probe", _boom)
    health = await p.health_check()
    assert health.status == "down"


async def test_pytdx_missing_price_raises(monkeypatch) -> None:
    p = PytdxProvider(hosts=[("127.0.0.1", 7709)])
    api = MagicMock()
    api.get_security_quotes.return_value = [{"code": "000001", "name": "平安银行", "price": None}]
    api.connect.return_value = True
    monkeypatch.setattr(p, "_connect", lambda: api)
    with pytest.raises(ProviderBadResponseError):
        await p.get_quote("000001", "CN")
