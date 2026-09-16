"""T306 AKShareProvider（A 股行情/财务/新闻，基于 akshare SDK）。

数据源：akshare（https://github.com/akfamily/akshare）—— 聚合多家公开数据源
的新浪/东财接口。本 Provider 仅在该 Provider 层访问 SDK（AGENTS.md §4），上层统一经
Provider Registry 交互，agent 永不直接 import。

实现说明：
- SDK 为同步库，统一用 ``asyncio.to_thread`` 包裹，避免阻塞事件循环后再经
  ``BaseProvider._call`` 在 ``self.timeout`` 窗口内执行；
- SDK 超时映射 ProviderTimeoutError，其它 SDK 异常映射 ProviderBadResponseError；
- akshare 采用延迟 import（函数内导入），未安装/加载失败映射为 ProviderBadResponseError。

诚实标注：akshare 接口返回列名随版本与目标数据源波动较大，下列字段映射按常见输出
编写，未经真实网络样本实测，统一以『SDK 字段待实测校准』标注，落地前需以真实样本
校准（AGENTS.md §10）。
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from decimal import Decimal
from typing import Any

from finsage.exceptions import ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .eastmoney_patch import apply_eastmoney_patch
from .normalize import normalize_market, normalize_period

logger = logging.getLogger(__name__)

# 财务指标 -> (stock_financial_abstract 指标名, 单位, 币种)。
# 基于 stock_financial_abstract（按报告期分列，含 营业总收入/归母净利润/毛利率 等）。
# 币种指标换算为亿元（value/1e8），百分比指标保留原值。
_FINANCIAL_ABSTRACT_METRICS: dict[str, tuple[str, str, str | None]] = {
    "revenue": ("营业总收入", "亿元", "CNY"),
    "net_income": ("归母净利润", "亿元", "CNY"),
    "gross_margin": ("毛利率", "%", None),
    "net_margin": ("销售净利率", "%", None),
    "roe": ("净资产收益率(ROE)", "%", None),
    "debt_ratio": ("资产负债率", "%", None),
    "revenue_growth": ("营业总收入增长率", "%", None),
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


def _parse_dt(value: Any) -> datetime | None:
    """解析 SDK 时间文本；失败返回 None（不阻断整条记录）。【SDK 字段待实测校准】"""
    text = _clean_str(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _period_type(date_text: str) -> str:
    """按报告期结束日推断 period_type；无法识别落 DATE。"""
    if date_text.endswith("-12-31"):
        return "FY"
    if "-03-31" in date_text:
        return "Q1"
    if "-06-30" in date_text:
        return "Q2"
    if "-09-30" in date_text:
        return "Q3"
    return "DATE"


def _exchange_label(market: str, code: str) -> str:
    """按规范市场 + 代码首位数给交易所标签；无法推断返回规范市场。"""
    norm = normalize_market(market)
    if norm == "CN":
        return "CN.SH" if code.startswith(("5", "6", "9")) else "CN.SZ"
    return norm


def _kv_from_frame(frame: Any) -> dict[str, Any]:
    """把 stock_individual_info_em 的响应摊成 {item: value}。"""
    kv: dict[str, Any] = {}
    for _, row in frame.iterrows():
        key = str(row.get("item", "") or "").strip()
        if key:
            kv[key] = row.get("value")
    return kv


class AKShareProvider(BaseProvider):
    """A 股行情/财务/新闻 Provider（T306）。

    ``name="akshare"``，``capability_prefix="akshare"``。实现
    FinancialDataProvider 契约五个异步方法，返回 domain 对象。
    """

    name = "akshare"
    capability_prefix = "akshare"

    # 东财反爬补丁开启时，每次请求会随机休眠 1-4s；get_quote 已改为单股精准取数
    # （stock_individual_info_em），但补丁的逐请求休眠仍会拉长耗时，故补丁开启时
    # 默认超时放宽到 120s。
    _PATCHED_TIMEOUT = 120.0

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
        """延迟加载 akshare SDK；缺失时抛 ProviderBadResponseError。"""
        try:
            import akshare as ak  # noqa: PLC0415 - 延迟 import
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise ProviderBadResponseError("akshare SDK is not installed") from exc
        return ak

    # ---------- 契约实现 ----------

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """实时行情（§4.7）。【SDK 字段待实测校准】基于 stock_individual_info_em 的 最新/股票简称。

        单股精准取数：不再拉取全市场快照（stock_zh_a_spot_em 约 59 页），一次请求返回
        目标股票的 最新价 与 股票简称（该接口同时含 最新 与 股票简称 两列）。
        """
        ensure_symbol_market(symbol, market)
        sdk = self._load_sdk()
        code = _cn_code(symbol)
        frame = await self._call(
            "quote",
            asyncio.to_thread(sdk.stock_individual_info_em, symbol=code),
        )
        # 后处理异常保护（审计 §2.5）：frame 结构非预期时转 ProviderBadResponseError，
        # 进入 failover 链，而不是打穿整条降级链。
        kv: dict[str, Any] = self._guard_parse("quote", lambda: _kv_from_frame(frame))

        price = _to_decimal(kv.get("最新"), context="quote.price")
        if price is None:
            raise ProviderBadResponseError(f"{self.name}.quote: missing price for {symbol}")
        return Quote(
            symbol=symbol,
            market=normalize_market(market),
            name=_clean_str(kv.get("股票简称")),
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """财务指标（§4.6）。基于 stock_financial_abstract（按报告期分列）。

        币种指标换算为亿元；百分比指标保留原值。按请求 period 过滤（FY=年报），
        每个指标只保留最近一个报告期（财务摘要用）。
        """
        ensure_symbol_market(symbol, market)
        sdk = self._load_sdk()
        code = _cn_code(symbol)
        frame = await self._call(
            "financials",
            asyncio.to_thread(sdk.stock_financial_abstract, symbol=code),
        )

        norm_market = normalize_market(market)
        retrieved = utcnow()
        # 指标名 -> 行
        metric_rows: dict[str, Any] = {}
        for _, row in frame.iterrows():
            name = str(row.get("指标", "") or "").strip()
            if name:
                metric_rows[name] = row
        # 报告期列：形如 YYYYMMDD
        period_cols = [c for c in frame.columns if str(c).isdigit() and len(str(c)) == 8]

        metrics: list[FinancialMetric] = []
        for metric, (indicator, unit, currency) in _FINANCIAL_ABSTRACT_METRICS.items():
            row = metric_rows.get(indicator)
            if row is None:
                continue
            for col in period_cols:
                value = _to_decimal(row.get(col), context=f"financials.{metric}")
                if value is None:
                    continue
                col_text = str(col)
                date_text = f"{col_text[:4]}-{col_text[4:6]}-{col_text[6:8]}"
                ptype = _period_type(date_text)
                if unit == "亿元":
                    value = value / Decimal("100000000")
                metrics.append(
                    FinancialMetric(
                        company=symbol,
                        ticker=symbol,
                        market=norm_market,
                        metric=metric,
                        value=value,
                        currency=currency,
                        unit=unit,
                        period=normalize_period(date_text),
                        period_type=ptype,  # type: ignore[arg-type]
                        source=self.name,
                        retrieved_at=retrieved,
                    )
                )
        return _period_filter(metrics, period)

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """公司概况。基于 stock_individual_info_em 的 item/value。

        【SDK 字段待实测校准】仅 股票简称/行业 可靠，其余字段置空。
        """
        ensure_symbol_market(symbol, market)
        sdk = self._load_sdk()
        code = _cn_code(symbol)
        frame = await self._call(
            "company_profile",
            asyncio.to_thread(sdk.stock_individual_info_em, symbol=code),
        )
        kv: dict[str, Any] = {}
        for _, row in frame.iterrows():
            key = str(row.get("item", "") or "").strip()
            if key:
                kv[key] = row.get("value")
        name = _clean_str(kv.get("股票简称")) or symbol
        norm_market = normalize_market(market)
        return CompanyProfile(
            symbol=symbol,
            market=norm_market,
            name=name,
            currency="CNY",
            industry=_clean_str(kv.get("行业")),
            country="CN",
            exchange=_exchange_label(norm_market, code),
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """公司新闻。基于 stock_news_em，截取前 limit 条。

        【SDK 字段待实测校准】依赖列：新闻标题/新闻内容/发布时间/新闻链接。
        """
        ensure_symbol_market(symbol, market)
        sdk = self._load_sdk()
        code = _cn_code(symbol)
        frame = await self._call("news", asyncio.to_thread(sdk.stock_news_em, symbol=code))
        norm_market = normalize_market(market)
        retrieved = utcnow()
        items: list[NewsItem] = []
        for _, row in frame.iterrows():
            title = _clean_str(row.get("新闻标题"))
            if not title:
                continue
            items.append(
                NewsItem(
                    symbol=symbol,
                    market=norm_market,
                    title=title,
                    url=_clean_str(row.get("新闻链接")),
                    published_at=_parse_dt(row.get("发布时间")),
                    source=self.name,
                    summary=_clean_str(row.get("新闻内容")),
                    retrieved_at=retrieved,
                )
            )
            if len(items) >= limit:
                break
        return items

    async def health_check(self) -> ProviderHealth:
        """健康检查：以一次轻量探活标记 status/success_rate。"""
        capability = self._capability("quote")
        updated = utcnow()
        try:
            await self._run_blocking(self._sdk_probe)
        except Exception as exc:  # noqa: BLE001 - 探活失败统一归 down
            logger.warning("akshare_health_failed", extra={"extra": {"error": type(exc).__name__}})
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
        sdk = AKShareProvider._load_sdk()
        return sdk.tool_trade_date_hist_sina()


def _period_filter(metrics: list[FinancialMetric], period: str) -> list[FinancialMetric]:
    """按请求 period 过滤指标；未指定请求周期时返回全部。

    - ``FY`` → 只保留年报（period_type == "FY"）；
    - 其它（如 "2024"）→ 按归一化 period 精确匹配。
    过滤后每个指标只保留最近一个报告期（财务摘要用）。
    """
    if not period:
        return metrics
    target = normalize_period(period)
    if target == "FY":
        filtered = [m for m in metrics if m.period_type == "FY"]
    else:
        filtered = [m for m in metrics if m.period == target]
    latest: dict[str, FinancialMetric] = {}
    for m in filtered:
        if m.metric not in latest or m.period > latest[m.metric].period:
            latest[m.metric] = m
    return list(latest.values())


__all__ = ["AKShareProvider"]