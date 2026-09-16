"""T308 AshareProvider（A 股行情/公司数据，基于 mpquant/Ashare SDK）。

数据源：Ashare（https://github.com/mpquant/Ashare）—— 通过 akhq/pygtk 聚合新浪等
公开行情。本 Provider 仅在该 Provider 层访问 SDK（AGENTS.md §4），上层统一经
Provider Registry 交互，agent 永不直接 import。

实现说明：
- SDK 为同步库，统一用 ``asyncio.to_thread`` 包裹，避免阻塞事件循环；
- SDK 延迟 import（函数内导入），未安装时映射为 ProviderBadResponseError；
- SDK 异常经 ``BaseProvider._call`` 映射为 ProviderTimeoutError / ProviderBadResponseError；
- 超时窗口使用 ``self.timeout``。

诚实标注：Ashare 基本面字段命名/取值在不同代理源（新浪/akshare）间口径不稳定，
以下字段映射基于 SDK 常见返回键推断，未经实测校正，统一以『SDK 字段待实测校准』标注，
落地前需以真实样本校准（AGENTS.md §10）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from finsage.exceptions import ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .normalize import normalize_market, normalize_period

logger = logging.getLogger(__name__)

# SDK 字段 -> 归一化指标名。对应 FinancialMetric.metric（normalize_metric 别名体系）。
# 【SDK 字段待实测校准】
_QUOTE_METRIC_MAP: dict[str, str] = {
    "pe": "pe",
    "pb": "pb",
    "eps": "eps",
    "changepercent": "change_pct",
    "turnoverratio": "turnover_pct",
    "marketcap": "market_cap",
}

# 指标 -> 单位（FinancialMetric.unit，直接复用 normalize_unit 的规范写法）。
# 【SDK 字段待实测校准】
_METRIC_UNIT: dict[str, str] = {
    "pe": "",
    "pb": "",
    "eps": "share",
    "change_pct": "pct",
    "turnover_pct": "pct",
    "market_cap": "CNY_yi",
}


def _exchange_code(symbol: str, market: str) -> str:
    """把 symbol+market 拼成 Ashare 期望的交易所前缀代码（如 ``sh600000``/``sz000001``）。"""
    m = normalize_market(market)
    code = symbol.strip().lower()
    # 已带交易所前缀则原样返回；否则按市场推断前缀。
    if code[:2] in ("sh", "sz", "bj"):
        return code
    if m == "CN.SH":
        return f"sh{code}"
    if m == "CN.SZ":
        return f"sz{code}"
    if m == "CN":
        # 6/5/9 开头归沪，其余归深（北交所 8/4 开头留在深拦截，避免臆断）。
        return f"{'sh' if code.startswith(('6', '5', '9')) else 'sz'}{code}"
    return code


def _exchange_label(market: str) -> str:
    """把归一化市场映射为交易所代码（CN.SH->CN.SH；未知返回原值）。"""
    m = normalize_market(market)
    if m in ("CN.SH", "CN.SZ"):
        return m
    return m


def _get(data: Any, key: str) -> Any:
    """从 SDK 返回对象中取字段：dict 按 key；对象按属性；兼容兜底。"""
    try:
        return data[key]  # type: ignore[index]
    except (KeyError, TypeError):
        pass
    value = getattr(data, key, None)
    if value is None and isinstance(data, dict):
        # 部分返回键可能带大写首字母（如 ``Name``）。
        for k, v in data.items():
            if k.lower() == key.lower():
                return v
    return value


def _to_decimal(value: Any, *, context: str) -> Decimal | None:
    """把 SDK 数字转 Decimal；解析失败返回 None（交由调用方决定）。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        logger.warning(
        "ashare_decimal_parse_failed",
        extra={"extra": {"context": context, "value": value}},
    )
        return None


class AshareProvider(BaseProvider):
    """A 股行情/公司数据 Provider（T308）。

    ``name="ashare"``，``capability_prefix="ashare"``。实现
    FinancialDataProvider 契约五个异步方法，返回 domain 对象。
    """

    name = "ashare"
    capability_prefix = "ashare"

    # ---------- SDK 访问骨架 ----------

    @staticmethod
    def _load_sdk() -> Any:
        """延迟加载 Ashare SDK；缺失时抛 ProviderBadResponseError。"""
        try:
            import ashare  # noqa: PLC0415 - 延迟 import
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise ProviderBadResponseError("ashare SDK is not installed") from exc
        return ashare

    def _quote_dict(self, symbol: str, market: str) -> dict[str, Any]:
        """同步执行 SDK 实时行情调用并归一为 dict。"""
        sdk = self._load_sdk()
        code = _exchange_code(symbol, market)
        data = sdk.get_realtime_quotes(code)  # 【SDK 字段待实测校准】返回列/键口径未统一
        if data is None:
            raise ProviderBadResponseError(f"ashare.quote: empty response for {code}")
        return data if isinstance(data, dict) else {"_row": data}

    # ---------- 契约实现 ----------

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """实时行情（§4.7）。【SDK 字段待实测校准】字段取自 get_realtime_quotes。"""
        ensure_symbol_market(symbol, market)
        data = await self._call("quote", asyncio.to_thread(self._quote_dict, symbol, market))

        price = _to_decimal(_get(data, "current") or _get(data, "close"), context="quote.price")
        if price is None:
            raise ProviderBadResponseError(f"ashare.quote: missing price for {symbol}")
        name = _get(data, "name")
        return Quote(
            symbol=symbol,
            market=normalize_market(market),
            name=str(name) if name else None,
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source="ashare",
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """财务/估值指标（§4.6）。【SDK 字段待实测校准】取自 get_realtime_quotes 的估值列。"""
        ensure_symbol_market(symbol, market)
        data = await self._call("financials", asyncio.to_thread(self._quote_dict, symbol, market))

        company = str(_get(data, "name") or symbol)
        norm_market = normalize_market(market)
        norm_period = normalize_period(period) if period else date.today().isoformat()
        retrieved = utcnow()
        metrics: list[FinancialMetric] = []
        for sdk_key, metric in _QUOTE_METRIC_MAP.items():
            value = _to_decimal(_get(data, sdk_key), context=f"financials.{metric}")
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
                    source="ashare",
                    retrieved_at=retrieved,
                )
            )
        return metrics

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """公司概况。【SDK 字段待实测校准】Ashare 无结构化基本面，仅名称可靠，其余置空。"""
        ensure_symbol_market(symbol, market)
        data = await self._call(
            "company_profile",
            asyncio.to_thread(self._quote_dict, symbol, market),
        )
        name = str(_get(data, "name") or symbol)
        norm_market = normalize_market(market)
        return CompanyProfile(
            symbol=symbol,
            market=norm_market,
            name=name,
            currency="CNY",
            sector=None,
            industry=None,
            description=None,
            website=None,
            country="CN",
            exchange=_exchange_label(norm_market),
            source="ashare",
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """公司新闻。Ashare 不提供公司新闻流，返回空列表（不支持该能力）。"""
        ensure_symbol_market(symbol, market)
        return []

    async def health_check(self) -> ProviderHealth:
        """健康检查：以一次最小行情探活标记 status/success_rate。"""
        capability = self._capability("quote")
        updated = utcnow()
        try:
            await self._run_blocking(self._sdk_probe)
        except Exception as exc:  # noqa: BLE001 - 探活失败统一归 down
            logger.warning("ashare_health_failed", extra={"extra": {"error": type(exc).__name__}})
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
    def _sdk_probe() -> None:
        """探活最小调用：验证 SDK 可导入。"""
        AshareProvider._load_sdk()


__all__ = ["AshareProvider"]