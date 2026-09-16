"""Provider 归一化 & 冲突比对单测（T311 一部分，unit）。"""

from __future__ import annotations

from decimal import Decimal

from finsage.providers.finance import (
    compare,
    normalize_currency,
    normalize_definition,
    normalize_market,
    normalize_metric,
    normalize_period,
    normalize_symbol,
    normalize_unit,
)
from finsage.providers.finance.conflict import FinancialValue

# ---- §11 normalization ----


def test_normalize_symbol_strips_separators():
    assert normalize_symbol("600-519") == "600519"
    assert normalize_symbol(" aapl ") == "AAPL"


def test_normalize_market_aliases():
    assert normalize_market("SH") == "CN.SH"
    assert normalize_market("szse") == "CN.SZ"
    assert normalize_market("NYSE") == "US"
    assert normalize_market("XA") == "XA"


def test_normalize_metric_aliases():
    assert normalize_metric("营业收入") == "revenue"
    assert normalize_metric("Revenue") == "revenue"
    assert normalize_metric("净利润") == "net_income"
    assert normalize_metric("custom_metric") == "custom_metric"


def test_normalize_currency():
    assert normalize_currency("RMB") == "CNY"
    assert normalize_currency("¥") == "CNY"
    assert normalize_currency("USD") == "USD"
    assert normalize_currency("") == "UNKNOWN"


def test_normalize_unit():
    assert normalize_unit("亿元") == "CNY_yi"
    assert normalize_unit("万") == "CNY_wan"
    assert normalize_unit("%") == "pct"
    assert normalize_unit("weird") == "weird"


def test_normalize_period():
    assert normalize_period("2025Q1") == "2025Q1"
    assert normalize_period("FY2024") == "2024"
    assert normalize_period("2025-03-31") == "2025-03-31"
    assert normalize_period("2024年报") == "2024"


def test_normalize_definition():
    assert normalize_definition("  Net  Income ") == "net income"


# ---- §11 conflict detection ----


def _vticker(**overrides) -> FinancialValue:
    base = {
        "company": "Example Corp",
        "ticker": "600519",
        "market": "CN.SH",
        "metric": "net_income",
        "value": Decimal("100"),
        "currency": "CNY",
        "unit": "CNY_yi",
        "period": "2024",
        "definition": "net income",
    }
    base.update(overrides)
    return FinancialValue(**base)


def test_compare_match_exact():
    assert compare(_vticker(), _vticker()) == "MATCH"


def test_compare_match_within_tolerance():
    a = _vticker(value=Decimal("100"))
    b = _vticker(value=Decimal("100.3"))  # 0.3% 差异
    assert compare(a, b) == "MATCH"


def test_compare_conflict_over_tolerance():
    a = _vticker(value=Decimal("100"))
    b = _vticker(value=Decimal("90"))  # 10% 差异
    assert compare(a, b) == "CONFLICT"


def test_compare_not_comparable_diff_metric():
    a = _vticker(metric="net_income")
    b = _vticker(metric="revenue")
    assert compare(a, b) == "NOT_COMPARABLE"


def test_compare_not_comparable_diff_period():
    a = _vticker(period="2024")
    b = _vticker(period="2023")
    assert compare(a, b) == "NOT_COMPARABLE"


def test_compare_insufficient_missing_key():
    a = _vticker(unit=None)
    b = _vticker()
    assert compare(a, b) == "INSUFFICIENT"


def test_compare_currency_aliases_match():
    a = _vticker(currency="CNY")
    b = _vticker(currency="RMB")
    assert compare(a, b) == "MATCH"