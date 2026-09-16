"""T309 YFinance Provider。

基于 yfinance SDK 实现 FinancialDataProvider 契约（§9.1）。
SDK 为同步调用，统一用 asyncio.to_thread 包裹到独立线程再经 BaseProvider._call
在 self.timeout 窗口内执行；超时映射 ProviderTimeoutError，其它 SDK 异常映射
ProviderBadResponseError（见 base._call / _map_sdk_error）。

yfinance 采用延迟 import，避免未安装/未初始化时把加载阻塞在模块导入路径上。
字段映射依据 yfinance 常见返回记录，部分字段（info 键、财务表行名）依赖数据源内部
命名，未在本仓库用真实网络数据实测 —— 相关 docstring 均标注「SDK 字段待实测校准」。

金融数字均来自 SDK 原生数值，直接转为 Decimal，不做 LLM 计算（AGENTS.md §3）。
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from finsage.exceptions import NormalizationError, ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote

# 财务表行名 → 规范指标名。yfinance 行列名依赖数据源内部命名，待实测校准。
_FINANCIAL_ROWS: dict[str, str] = {
    "Total Revenue": "revenue",
    "Net Income": "net_income",
    "Gross Profit": "gross_profit",
    "Operating Income": "operating_income",
    "Total Assets": "total_assets",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Stockholders Equity": "equity",
}


class YFinanceProvider(BaseProvider):
    """基于 yfinance 的金融数据 Provider。"""

    name: str = "yfinance"
    capability_prefix: str = "yfinance"

    def _sdk(self) -> Any:
        """延迟导入并返回 yfinance 模块。"""
        import yfinance  # type: ignore[import-untyped]

        return yfinance

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        """把 SDK 数值安全转换为 Decimal；空值/非数值/非有限值视为缺失。"""
        if value is None:
            raise NormalizationError("missing value")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise NormalizationError(f"non-numeric value: {value!r}") from None
        if math.isnan(number) or math.isinf(number):
            raise NormalizationError(f"non-finite value: {value!r}")
        return Decimal(repr(number))

    def _currency(self, ticker: Any) -> str | None:
        info = ticker.info if hasattr(ticker, "info") else {}
        currency = info.get("currency") if isinstance(info, dict) else None
        return currency if isinstance(currency, str) and currency else None

    async def get_quote(self, symbol: str, market: str) -> Quote:
        ensure_symbol_market(symbol, market)
        sdk = self._sdk()
        yf_ticker = sdk.Ticker(symbol)
        captured: dict[str, Any] = {}

        def _fetch() -> None:
            fast = yf_ticker.fast_info
            price = fast.last_price if not math.isnan(fast.last_price) else None
            if price is None:
                price = yf_ticker.info.get("regularMarketPrice")
            if price is None:
                price = yf_ticker.info.get("regularMarketPreviousClose")
            captured["price"] = price
            captured["name"] = yf_ticker.info.get("shortName") or yf_ticker.info.get("longName")

        await self._call("quote", asyncio.to_thread(_fetch))
        # SDK 字段待实测校准：price 取 fast_info.last_price，失败回退 info 键。
        price = captured["price"]
        if price is None:
            raise ProviderBadResponseError("quote price unavailable")
        return Quote(
            symbol=symbol,
            market=market,
            name=captured.get("name"),
            price=self._to_decimal(price),
            currency=self._currency(yf_ticker) or "USD",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        ensure_symbol_market(symbol, market)
        sdk = self._sdk()
        yf_ticker = sdk.Ticker(symbol)
        currency = self._currency(yf_ticker)

        def _fetch() -> Any:
            try:
                return yf_ticker.get_income_stmt(period)
            except TypeError:  # SDK 版本差异：参数名待实测校准
                return yf_ticker.get_income_stmt()

        table = await self._call("financials", asyncio.to_thread(_fetch))
        if table is None or table.empty:
            return []

        metrics: list[FinancialMetric] = []
        retrieved_at = utcnow()
        for label, metric in _FINANCIAL_ROWS.items():
            if label not in table.index:
                continue
            for period_end in table.columns:
                try:
                    value = self._to_decimal(table.loc[label, period_end])
                except NormalizationError:
                    continue
                metrics.append(
                    FinancialMetric(
                        company=_company_name(yf_ticker),
                        ticker=symbol,
                        market=market,
                        metric=metric,
                        value=value,
                        currency=currency,
                        period=_period_str(period_end),
                        period_type=_period_type(period_end),
                        source=self.name,
                        retrieved_at=retrieved_at,
                    )
                )
        return metrics

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        ensure_symbol_market(symbol, market)
        sdk = self._sdk()
        yf_ticker = sdk.Ticker(symbol)

        def _fetch() -> dict[str, Any]:
            return yf_ticker.info

        info = await self._call("company_profile", asyncio.to_thread(_fetch))
        return CompanyProfile(
            symbol=symbol,
            market=market,
            name=info.get("longName") or info.get("shortName") or symbol,
            currency=info.get("currency"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            description=info.get("longBusinessSummary"),
            website=info.get("website"),
            country=info.get("country"),
            exchange=info.get("exchange"),
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        ensure_symbol_market(symbol, market)
        sdk = self._sdk()
        yf_ticker = sdk.Ticker(symbol)

        def _fetch() -> Any:
            return yf_ticker.news

        news = await self._call("news", asyncio.to_thread(_fetch)) or []
        items: list[NewsItem] = []
        retrieved_at = utcnow()
        for entry in news[:limit]:
            published = entry.get("providerPublishTime") or entry.get("providerPublishDate")
            published_at = None
            if isinstance(published, (int, float)):
                published_at = datetime.fromtimestamp(published, tz=UTC)
            items.append(
                NewsItem(
                    symbol=symbol,
                    market=market,
                    title=str(entry.get("title")),
                    url=entry.get("link"),
                    published_at=published_at,
                    source=self.name,
                    summary=entry.get("summary"),
                    retrieved_at=retrieved_at,
                )
            )
        return items

    async def health_check(self) -> ProviderHealth:
        """以一次轻量行情抓取探测 yfinance 可用性。"""
        capability = self._capability("quote")
        now = utcnow()
        try:
            await self.get_quote("AAPL", "US")
        except Exception:  # noqa: BLE001 - 健康探测按结果归类状态
            return ProviderHealth(
                provider_name=self.name,
                capability=capability,
                status="down",
                success_rate=Decimal("0.000000"),
                last_failure_at=now,
                failure_count=1,
                updated_at=now,
            )
        return ProviderHealth(
            provider_name=self.name,
            capability=capability,
            status="healthy",
            success_rate=Decimal("1.000000"),
            last_success_at=now,
            updated_at=now,
        )


def _company_name(ticker: Any) -> str:
    """提取公司名用于 FinancialMetric.company；info 键待实测校准。"""
    info = ticker.info if hasattr(ticker, "info") else {}
    if isinstance(info, dict):
        return info.get("shortName") or info.get("longName") or ""
    return ""


def _period_str(period_end: Any) -> str:
    """报告期列转字符串；映射待实测校准。"""
    if isinstance(period_end, datetime):
        return period_end.strftime("%Y-%m-%d")
    return str(period_end)


def _period_type(period_end: Any) -> str:
    """报告期列决定 period_type；映射待实测校准。"""
    text = _period_str(period_end).upper()
    for quarter in ("Q4", "Q3", "Q2", "Q1"):
        if quarter in text:
            return quarter
    return "DATE"