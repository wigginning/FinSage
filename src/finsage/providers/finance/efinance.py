"""EFinanceProvider（A 股行情/财务/公司数据，基于 efinance SDK）。

数据源：efinance（https://github.com/Micro-sheep/efinance）—— 东方财富公开数据
的免费封装，无需 token、无需注册。参考 daily_stock_analysis 的 EfinanceFetcher
（Priority 0，最高优先级）引入，作为 A 股可用免费源。

实现说明：
- SDK 为同步库，统一用 ``asyncio.to_thread`` 包裹，避免阻塞事件循环后再经
  ``BaseProvider._call`` 在 ``self.timeout`` 窗口内执行；
- SDK 延迟 import（函数内导入），未安装/加载失败映射为 ProviderBadResponseError；
- 仅覆盖 A 股（CN/CN.SH/CN.SZ）；新闻接口该源不提供，get_news 返回空列表。

诚实标注：efinance 返回列名随版本与东财接口波动较大，下列字段映射按常见输出编写，
未经真实网络样本实测，统一以『SDK 字段待实测校准』标注，落地前需以真实样本校准
（AGENTS.md §10）。
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date
from decimal import Decimal
from typing import Any

from finsage.exceptions import ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .eastmoney_patch import apply_eastmoney_patch
from .normalize import normalize_market, normalize_period

logger = logging.getLogger(__name__)

# 实时行情估值列 -> 规范指标名。efinance get_realtime_quotes 常见列名。
# 【SDK 字段待实测校准】
_QUOTE_METRIC_MAP: dict[str, str] = {
    "市盈率-动态": "pe",
    "市净率": "pb",
    "总市值": "market_cap",
    "换手率": "turnover_pct",
}

# 指标 -> 单位（复用 normalize_unit 的规范写法）。
_METRIC_UNIT: dict[str, str] = {
    "pe": "",
    "pb": "",
    "market_cap": "CNY_yi",
    "turnover_pct": "pct",
}


def _cn_code(symbol: str) -> str:
    """提取 A 股 6 位数字代码（容忍 SH600519 / 600519.SH 等带前缀写法）。"""
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits or str(symbol)


def _to_decimal(value: Any, *, context: str) -> Decimal | None:
    """把 SDK 数值转 Decimal；空值/非数值/非有限值返回 None（交由调用方决定）。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return Decimal(str(number))


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _exchange_label(market: str, code: str) -> str:
    """按规范市场 + 代码首位数给交易所标签；无法推断返回规范市场。"""
    norm = normalize_market(market)
    if norm == "CN":
        return "CN.SH" if code.startswith(("5", "6", "9")) else "CN.SZ"
    return norm


class EFinanceProvider(BaseProvider):
    """A 股行情/财务/公司数据 Provider（efinance，免费无 token）。

    ``name="efinance"``，``capability_prefix="efinance"``。实现
    FinancialDataProvider 契约五个异步方法，返回 domain 对象。
    """

    name = "efinance"
    capability_prefix = "efinance"

    # 东财反爬补丁开启时，每次请求会随机休眠 1-4s；多页拉取（get_realtime_quotes
    # 约 9 页）会显著拉长耗时，故补丁开启时默认超时放宽到 60s。
    _PATCHED_TIMEOUT = 60.0

    def __init__(
        self,
        *,
        timeout: float | None = None,
        enable_eastmoney_patch: bool = False,
    ) -> None:
        # 补丁开启且未显式指定超时时，用更宽的超时窗口。
        if enable_eastmoney_patch and timeout is None:
            timeout = self._PATCHED_TIMEOUT
        super().__init__(timeout=timeout)
        # 东财反爬补丁为 opt-in（默认关闭），仅显式开启时应用（见 eastmoney_patch 合规说明）。
        if enable_eastmoney_patch:
            apply_eastmoney_patch()

    # ---------- SDK 访问骨架 ----------

    @staticmethod
    def _load_sdk() -> Any:
        """延迟加载 efinance SDK；缺失时抛 ProviderBadResponseError。"""
        try:
            import efinance as ef  # noqa: PLC0415 - 延迟 import
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise ProviderBadResponseError("efinance SDK is not installed") from exc
        return ef

    def _quote_frame(self, symbol: str) -> Any:
        """同步执行实时行情调用并返回 DataFrame。"""
        sdk = self._load_sdk()
        code = _cn_code(symbol)
        frame = sdk.stock.get_realtime_quotes()  # 【SDK 字段待实测校准】
        if frame is None or frame.empty:
            raise ProviderBadResponseError(f"{self.name}.quote: empty response for {code}")
        matched = frame[frame["股票代码"].astype(str).str.zfill(6) == code]
        if matched.empty:
            raise ProviderBadResponseError(f"{self.name}.quote: no data for {code}")
        return matched.iloc[0]

    # ---------- 契约实现 ----------

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """实时行情（§4.7）。【SDK 字段待实测校准】基于 get_realtime_quotes。"""
        ensure_symbol_market(symbol, market)
        row = await self._call("quote", asyncio.to_thread(self._quote_frame, symbol))
        # 后处理异常保护（审计 §2.5）：row 结构非预期（如 None / 非映射）时转
        # ProviderBadResponseError，进入 failover 链而非打穿降级链。
        price = self._guard_parse(
            "quote", lambda: _to_decimal(row.get("最新价"), context="quote.price")
        )
        if price is None:
            raise ProviderBadResponseError(f"{self.name}.quote: missing price for {symbol}")
        return Quote(
            symbol=symbol,
            market=normalize_market(market),
            name=_clean_str(row.get("股票名称")),
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """财务/估值指标（§4.6）。【SDK 字段待实测校准】取自实时行情估值列。"""
        ensure_symbol_market(symbol, market)
        row = await self._call("financials", asyncio.to_thread(self._quote_frame, symbol))
        company = _clean_str(row.get("股票名称")) or symbol
        norm_market = normalize_market(market)
        norm_period = normalize_period(period) if period else date.today().isoformat()
        retrieved = utcnow()
        metrics: list[FinancialMetric] = []
        for sdk_key, metric in _QUOTE_METRIC_MAP.items():
            value = _to_decimal(row.get(sdk_key), context=f"financials.{metric}")
            if value is None:
                continue
            unit = _METRIC_UNIT[metric]
            metrics.append(
                FinancialMetric(
                    company=company,
                    ticker=symbol,
                    market=norm_market,
                    metric=metric,
                    value=value,
                    currency="CNY" if metric == "market_cap" else None,
                    unit=unit or None,
                    period=norm_period,
                    period_type="DATE",
                    source=self.name,
                    retrieved_at=retrieved,
                )
            )
        return metrics

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """公司概况。【SDK 字段待实测校准】仅名称可靠，其余置空。"""
        ensure_symbol_market(symbol, market)
        row = await self._call(
            "company_profile",
            asyncio.to_thread(self._quote_frame, symbol),
        )
        code = _cn_code(symbol)
        norm_market = normalize_market(market)
        return CompanyProfile(
            symbol=symbol,
            market=norm_market,
            name=_clean_str(row.get("股票名称")) or symbol,
            currency="CNY",
            sector=None,
            industry=None,
            description=None,
            website=None,
            country="CN",
            exchange=_exchange_label(norm_market, code),
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """公司新闻。efinance 不提供公司新闻流，返回空列表（不支持该能力）。"""
        ensure_symbol_market(symbol, market)
        return []

    async def health_check(self) -> ProviderHealth:
        """健康检查：以一次最小行情探活标记 status/success_rate。"""
        capability = self._capability("quote")
        updated = utcnow()
        try:
            await self._run_blocking(self._sdk_probe)
        except Exception as exc:  # noqa: BLE001 - 探活失败统一归 down
            logger.warning("efinance_health_failed", extra={"extra": {"error": type(exc).__name__}})
            return ProviderHealth(
                provider_name=self.name,
                capability=capability,
                status="down",
                success_rate=Decimal("0.0"),
                last_failure_at=updated,
                failure_count=1,
                updated_at=updated,
            )
        return ProviderHealth(
            provider_name=self.name,
            capability=capability,
            status="healthy",
            success_rate=Decimal("1.0"),
            last_success_at=updated,
            failure_count=0,
            updated_at=updated,
        )

    @staticmethod
    def _sdk_probe() -> Any:
        """探活最小调用：验证 SDK 可导入并返回轻量接口数据。"""
        sdk = EFinanceProvider._load_sdk()
        return sdk.stock.get_realtime_quotes()


__all__ = ["EFinanceProvider"]
