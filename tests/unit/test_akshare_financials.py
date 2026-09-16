"""AKShareProvider.get_financials 契约测试（§2.4 财务摘要）。

mock akshare SDK 的 stock_financial_abstract（按报告期分列），验证：
- 列名映射到 营业总收入/归母净利润/毛利率 等；
- 币种指标换算为亿元、百分比指标保留原值；
- period="FY" 只保留年报且每指标取最近一期。
不依赖真实网络（单元测试不发外部请求，合规）。
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd

from finsage.providers.finance import AKShareProvider


def _abstract_frame() -> pd.DataFrame:
    """模拟 stock_financial_abstract 返回（宁德时代 300750 示例值）。"""
    return pd.DataFrame(
        [
            {
                "选项": "常用指标",
                "指标": "营业总收入",
                "20251231": 4.0e11,
                "20241231": 3.5e11,
                "20250630": 1.8e11,
            },
            {
                "选项": "常用指标",
                "指标": "归母净利润",
                "20251231": 5.0e10,
                "20241231": 4.0e10,
                "20250630": 2.0e10,
            },
            {
                "选项": "常用指标",
                "指标": "毛利率",
                "20251231": 0.25,
                "20241231": 0.24,
                "20250630": 0.26,
            },
            {
                "选项": "常用指标",
                "指标": "资产负债率",
                "20251231": 0.6,
                "20241231": 0.62,
                "20250630": 0.58,
            },
        ]
    )


def _provider(monkeypatch) -> AKShareProvider:
    p = AKShareProvider()
    sdk = MagicMock()
    sdk.stock_financial_abstract.return_value = _abstract_frame()
    monkeypatch.setattr(
        "finsage.providers.finance.akshare.AKShareProvider._load_sdk",
        staticmethod(lambda: sdk),
    )
    return p


def _info_frame() -> pd.DataFrame:
    """模拟 stock_individual_info_em 返回（贵州茅台 600519 示例值）。"""
    return pd.DataFrame(
        [
            {"item": "最新", "value": 1305.18},
            {"item": "股票代码", "value": 600519},
            {"item": "股票简称", "value": "贵州茅台"},
            {"item": "行业", "value": "白酒Ⅱ"},
        ]
    )


def _quote_provider(monkeypatch) -> AKShareProvider:
    p = AKShareProvider()
    sdk = MagicMock()
    sdk.stock_individual_info_em.return_value = _info_frame()
    monkeypatch.setattr(
        "finsage.providers.finance.akshare.AKShareProvider._load_sdk",
        staticmethod(lambda: sdk),
    )
    return p


async def test_akshare_get_quote_single_stock(monkeypatch) -> None:
    """get_quote 单股精准取数：一次请求返回 最新价 与 股票简称，不拉全市场。"""
    p = _quote_provider(monkeypatch)
    quote = await p.get_quote("600519", "CN.SH")
    assert quote.symbol == "600519"
    assert quote.market == "CN.SH"
    assert quote.name == "贵州茅台"
    assert quote.price == Decimal("1305.18")
    assert quote.currency == "CNY"
    assert quote.source == "akshare"
    # 只调用单股接口，不调用全市场快照。
    sdk = p._load_sdk()
    sdk.stock_individual_info_em.assert_called_once_with(symbol="600519")
    sdk.stock_zh_a_spot_em.assert_not_called()


async def test_akshare_get_quote_missing_price_raises(monkeypatch) -> None:
    """最新价缺失时抛 ProviderBadResponseError。"""
    p = AKShareProvider()
    sdk = MagicMock()
    sdk.stock_individual_info_em.return_value = pd.DataFrame(
        [{"item": "股票简称", "value": "贵州茅台"}]
    )
    monkeypatch.setattr(
        "finsage.providers.finance.akshare.AKShareProvider._load_sdk",
        staticmethod(lambda: sdk),
    )
    try:
        await p.get_quote("600519", "CN.SH")
    except Exception as exc:  # noqa: BLE001
        assert type(exc).__name__ == "ProviderBadResponseError"
    else:  # pragma: no cover
        raise AssertionError("expected ProviderBadResponseError")


async def test_akshare_get_financials_fy(monkeypatch) -> None:
    p = _provider(monkeypatch)
    metrics = await p.get_financials("300750", "CN", "FY")
    by_metric = {m.metric: m for m in metrics}
    # 只保留年报，每指标最近一期（2025）。
    assert set(by_metric) == {"revenue", "net_income", "gross_margin", "debt_ratio"}
    assert all(m.period_type == "FY" for m in metrics)
    # 币种指标换算为亿元：4.0e11 / 1e8 = 4000.0
    assert by_metric["revenue"].value == Decimal("4000.0")
    assert by_metric["revenue"].unit == "亿元"
    assert by_metric["revenue"].currency == "CNY"
    assert by_metric["net_income"].value == Decimal("500.0")
    # 百分比指标保留原值
    assert by_metric["gross_margin"].value == Decimal("0.25")
    assert by_metric["gross_margin"].unit == "%"
    assert by_metric["debt_ratio"].value == Decimal("0.6")
    assert all(m.source == "akshare" for m in metrics)


async def test_akshare_get_financials_no_period_returns_all_periods(monkeypatch) -> None:
    p = _provider(monkeypatch)
    metrics = await p.get_financials("300750", "CN", "")
    revenue_periods = {m.period for m in metrics if m.metric == "revenue"}
    # 未指定 period 返回全部报告期（含年报与中报）。
    assert "2025-12-31" in revenue_periods
    assert "2025-06-30" in revenue_periods
