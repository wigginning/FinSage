"""PytdxProvider（A 股行情/公司数据，基于 pytdx SDK）。

数据源：pytdx（https://github.com/rainx/pytdx）—— 通达信行情服务器直连，免费、
无需 token、无配额限制。参考 daily_stock_analysis 的 PytdxFetcher（Priority 2）
引入，作为 A 股可用免费源。

实现说明：
- SDK 为同步库，统一用 ``asyncio.to_thread`` 包裹，避免阻塞事件循环后再经
  ``BaseProvider._call`` 在 ``self.timeout`` 窗口内执行；
- SDK 延迟 import（函数内导入），未安装/加载失败映射为 ProviderBadResponseError；
- 仅覆盖 A 股（CN/CN.SH/CN.SZ）；新闻接口该源不提供，get_news 返回空列表。

诚实标注：pytdx 返回字段名/口径依赖通达信协议，下列字段映射按常见输出编写，
未经真实网络样本实测，统一以『SDK 字段待实测校准』标注，落地前需以真实样本校准
（AGENTS.md §10）。
"""

from __future__ import annotations

import asyncio
import logging
import math
from decimal import Decimal
from typing import Any

from finsage.exceptions import ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .normalize import normalize_market

logger = logging.getLogger(__name__)

# 默认通达信行情服务器（参考 daily_stock_analysis 的 DEFAULT_HOSTS）。
_DEFAULT_HOSTS: list[tuple[str, int]] = [
    ("119.147.212.81", 7709),  # 深圳
    ("112.74.214.43", 7727),   # 深圳
    ("221.231.141.60", 7709),  # 上海
    ("101.227.73.20", 7709),   # 上海
    ("101.227.77.254", 7709),  # 上海
    ("14.215.128.18", 7709),   # 广州
    ("59.173.18.140", 7709),   # 武汉
    ("180.153.39.51", 7709),   # 杭州
]

# get_finance_info 字段 -> 规范指标名。pytdx 财务字段口径待实测校准。
_FINANCE_METRICS: dict[str, str] = {
    "pe": "pe",
    "pb": "pb",
    "total_capital": "market_cap",
}


def _cn_code(symbol: str) -> str:
    """提取 A 股 6 位数字代码（容忍 SH600519 / 600519.SH 等带前缀写法）。"""
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits or str(symbol)


def _market_code(symbol: str, market: str) -> tuple[int, str]:
    """返回 pytdx 市场代码（0=深圳，1=上海）与 6 位代码。"""
    code = _cn_code(symbol)
    m = normalize_market(market)
    if m == "CN.SH":
        return 1, code
    if m == "CN.SZ":
        return 0, code
    # CN 兜底：6/5/9 开头归沪，其余归深（北交所拦截，避免臆断）。
    return (1, code) if code.startswith(("6", "5", "9")) else (0, code)


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


class PytdxProvider(BaseProvider):
    """A 股行情/公司数据 Provider（pytdx，免费无 token）。

    ``name="pytdx"``，``capability_prefix="pytdx"``。实现
    FinancialDataProvider 契约五个异步方法，返回 domain 对象。
    """

    name = "pytdx"
    capability_prefix = "pytdx"

    def __init__(
        self,
        *,
        hosts: list[tuple[str, int]] | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self._hosts = hosts or _DEFAULT_HOSTS

    # ---------- SDK 访问骨架 ----------

    @staticmethod
    def _load_sdk() -> Any:
        """延迟加载 pytdx SDK；缺失时抛 ProviderBadResponseError。"""
        try:
            from pytdx.hq import TdxHq_API  # noqa: PLC0415 - 延迟 import
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise ProviderBadResponseError("pytdx SDK is not installed") from exc
        return TdxHq_API

    def _connect(self) -> Any:
        """连接首个可用通达信服务器，返回已连接的 api 实例。"""
        api_cls = self._load_sdk()
        api = api_cls()
        for host, port in self._hosts:
            try:
                if api.connect(host, port, time_out=5):
                    return api
            except Exception:  # noqa: BLE001 - 单服务器失败继续尝试下一个
                continue
        raise ProviderBadResponseError(f"{self.name}: no reachable TDX server")

    def _quote_row(self, symbol: str, market: str) -> dict[str, Any]:
        """同步执行实时行情调用并返回单行 dict。"""
        market_code, code = _market_code(symbol, market)
        api = self._connect()
        try:
            data = api.get_security_quotes([(market_code, code)])
            if not data:
                raise ProviderBadResponseError(f"{self.name}.quote: no data for {code}")
            return data[0]
        finally:
            api.disconnect()

    def _finance_info(self, symbol: str, market: str) -> dict[str, Any]:
        """同步执行财务信息调用并返回 dict。"""
        market_code, code = _market_code(symbol, market)
        api = self._connect()
        try:
            info = api.get_finance_info(market_code, code)
            if not info:
                raise ProviderBadResponseError(f"{self.name}.profile: no data for {code}")
            return info
        finally:
            api.disconnect()

    # ---------- 契约实现 ----------

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """实时行情（§4.7）。【SDK 字段待实测校准】基于 get_security_quotes。"""
        ensure_symbol_market(symbol, market)
        row = await self._call("quote", asyncio.to_thread(self._quote_row, symbol, market))
        price = _to_decimal(row.get("price"), context="quote.price")
        if price is None:
            raise ProviderBadResponseError(f"{self.name}.quote: missing price for {symbol}")
        return Quote(
            symbol=symbol,
            market=normalize_market(market),
            name=_clean_str(row.get("name")),
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """财务/估值指标（§4.6）。【SDK 字段待实测校准】取自 get_finance_info。"""
        ensure_symbol_market(symbol, market)
        info = await self._call("financials", asyncio.to_thread(self._finance_info, symbol, market))
        norm_market = normalize_market(market)
        retrieved = utcnow()
        metrics: list[FinancialMetric] = []
        for sdk_key, metric in _FINANCE_METRICS.items():
            value = _to_decimal(info.get(sdk_key), context=f"financials.{metric}")
            if value is None:
                continue
            metrics.append(
                FinancialMetric(
                    company=_clean_str(info.get("name")) or symbol,
                    ticker=symbol,
                    market=norm_market,
                    metric=metric,
                    value=value,
                    currency="CNY" if metric == "market_cap" else None,
                    unit="CNY_yi" if metric == "market_cap" else None,
                    period=period or "DATE",
                    period_type="DATE",
                    source=self.name,
                    retrieved_at=retrieved,
                )
            )
        return metrics

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """公司概况。【SDK 字段待实测校准】仅名称可靠，其余置空。"""
        ensure_symbol_market(symbol, market)
        info = await self._call(
            "company_profile",
            asyncio.to_thread(self._finance_info, symbol, market),
        )
        code = _cn_code(symbol)
        norm_market = normalize_market(market)
        return CompanyProfile(
            symbol=symbol,
            market=norm_market,
            name=_clean_str(info.get("name")) or symbol,
            currency="CNY",
            sector=None,
            industry=None,
            description=None,
            website=None,
            country="CN",
            exchange="CN.SH" if code.startswith(("6", "5", "9")) else "CN.SZ",
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """公司新闻。pytdx 不提供公司新闻流，返回空列表（不支持该能力）。"""
        ensure_symbol_market(symbol, market)
        return []

    async def health_check(self) -> ProviderHealth:
        """健康检查：以一次最小行情探活标记 status/success_rate。"""
        capability = self._capability("quote")
        updated = utcnow()
        try:
            await self._run_blocking(self._sdk_probe)
        except Exception as exc:  # noqa: BLE001 - 探活失败统一归 down
            logger.warning("pytdx_health_failed", extra={"extra": {"error": type(exc).__name__}})
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
        """探活最小调用：验证 SDK 可导入。"""
        PytdxProvider._load_sdk()


__all__ = ["PytdxProvider"]
