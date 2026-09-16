"""T310 Provider normalization（§11 — 比较前必须完成的七类归一化）。

提供 symbol / market / metric / currency / unit / period / definition 的确定性
归一化函数；归一化后的比较键 (company, ticker, market, metric, period, currency,
unit, definition) 供 T312 conflict detection 使用。

金融数字均为主观可验证的确定性字符串处理，不依赖 LLM（AGENTS.md §3）。
"""

from __future__ import annotations

import re

__all__ = [
    "normalize_symbol",
    "normalize_market",
    "normalize_metric",
    "normalize_currency",
    "normalize_unit",
    "normalize_period",
    "normalize_definition",
]


def _key(value: str) -> str:
    parts = re.split(r"[\s\-.]+", value.strip())
    return "".join(p for p in parts if p).upper()


def normalize_symbol(symbol: str) -> str:
    """股票代码归一化：去空白/连字符，转大写（不区分源格式）。"""
    return _key(symbol)


_market_aliases = {
    "CN": "CN", "CHINA": "CN", "A": "CN",
    "CN_SH": "CN.SH", "SH": "CN.SH", "SSE": "CN.SH", "CNSH": "CN.SH",
    "CN_SZ": "CN.SZ", "SZ": "CN.SZ", "SZSE": "CN.SZ", "CNSZ": "CN.SZ",
    "US": "US", "UNITED_STATES": "US", "NYSE": "US", "NASDAQ": "US",
    "HK": "HK", "HKEX": "HK", "HONG_KONG": "HK",
}


def normalize_market(market: str) -> str:
    """市场归一化：别名统一；未知市场原样大写（不做臆断映射）。"""
    return _market_aliases.get(_key(market), _key(market))


def _metric_aliases() -> dict[str, str]:
    """指标名别名统一为规范。新增规范化指标只能加别名，不改冻结契约。"""
    return {
        "REVENUE": "revenue", "营业收入": "revenue", "营收": "revenue",
        "NET_INCOME": "net_income", "净利润": "net_income", "归母净利润": "net_income",
        "TOTAL_ASSETS": "total_assets", "总资产": "total_assets", "资产总计": "total_assets",
        "TOTAL_LIABILITIES": "total_liabilities", "总负债": "total_liabilities",
        "EQUITY": "equity", "股东权益": "equity", "净资产": "equity",
        "TOTAL_REVENUE": "revenue", "OPERATING_REVENUE": "revenue",
        "GROSS_MARGIN": "gross_margin", "毛利率": "gross_margin",
        "EPS": "eps", "DILUTED_EPS": "eps",
        "PB": "pb", "PE": "pe", "PE_TTM": "pe_ttm",
    }


def normalize_metric(metric: str) -> str:
    """指标名归一化：别名统一；未知指标返回原样小写（保留，供冲突比对键使用）。"""
    key = metric.strip().upper()
    return _metric_aliases().get(key, metric.strip().lower())


def normalize_currency(currency: str) -> str:
    """货币归一化：转为三字代码；识别常见中文/符号写法（¥=CNY，$=USD，HK$=HKD）。"""
    upper = currency.strip().upper()
    if "¥" in upper:
        return "CNY"
    if upper.startswith("HK"):
        return "HKD"
    if "$" in upper:
        return "USD"
    # 仅保留字母，排掉括号备注
    alpha = "".join(ch for ch in upper if ch.isalpha())
    if alpha in ("CNY", "RMB", "RENMINBI"):
        return "CNY"
    if alpha in ("USD",):
        return "USD"
    if alpha in ("HKD", "USDHKD"):
        return "HKD"
    return alpha or "UNKNOWN"


def _unit_aliases() -> dict[str, str]:
    """数值单位归一化。未知单位保留小写（不做臆断）。"""
    return {
        "YUAN": "CNY", "CNY": "CNY", "RMB": "CNY", "元": "CNY",
        "USD": "USD", "DOLLAR": "USD", "美元": "USD",
        "HKD": "HKD", "港币": "HKD",
        "WAN": "CNY_wan", "万": "CNY_wan", "万元": "CNY_wan",
        "YI": "CNY_yi", "亿": "CNY_yi", "亿元": "CNY_yi",
        "M": "usd_m", "MILLION": "usd_m",
        "B": "usd_b", "BILLION": "usd_b",
        "%": "pct", "PERCENT": "pct", "比率": "pct",
        "SHARE": "share", "股": "share",
    }


def normalize_unit(unit: str) -> str:
    """数值单位归一化（元/万/亿/%/股 等）。"""
    return _unit_aliases().get(unit.strip().upper(), unit.strip().lower())


_PERIOD_Q = re.compile(r"(\d{4})\s*[Qq]([1-4])")
_PERIOD_FY = re.compile(r"FY\s*(\d{4})", re.IGNORECASE)
_YEAR = re.compile(r"(\d{4})")


def normalize_period(period: str) -> str:
    """报告期归一化：统一为 {YYYY} / {YYYY}Q{n} / {YYYY}-{MM}-{DD}。

    仅识别数值年份与季度；无法识别时返回原样（供冲突比对，不做臆断）。
    """
    text = period.strip()
    m = _PERIOD_Q.search(text)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    m = _PERIOD_FY.search(text)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    m = _YEAR.search(text)
    if m:
        return m.group(1)
    return text


def normalize_definition(definition: str) -> str:
    """指标定义归一化：压缩空白、统一小写；仅用于比对键。"""
    return re.sub(r"\s+", " ", definition.strip()).lower()