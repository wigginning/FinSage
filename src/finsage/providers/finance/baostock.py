"""T307 BaoStock Provider（A 股数据源，基于 Baostock SDK）。

实现 :class:`~finsage.providers.finance.base.FinancialDataProvider` 契约（§9.1）：
返回 domain.py 的 Pydantic 对象，不泄露 Baostock 原始数据结构；
SDK 为同步调用，统一用 asyncio.to_thread 包裹到独立线程再经 BaseProvider._call
在 self.timeout 窗口内执行；超时映射 ProviderTimeoutError，其它 SDK 异常映射
ProviderBadResponseError（见 base._call / _map_sdk_error）。

Baostock 采用延迟 import，避免未安装/未初始化时把加载阻塞在模块导入路径上。
Baostock 代码使用 sh./sz. 前缀（如 sh.600000），与工程内 symbol/market 分离的表示
不同，故以 ``_baostock_code`` 做代码转换。

字段映射依据 Baostock 官方示例给出最佳推测，但营收/净利润等字段的精确单位与口径
未在本仓库用真实网络数据实测 —— 相关 docstring 均以「SDK 字段待实测校准」标注
（遵循 AGENTS.md §10 诚实边界）。金融数字均来自 SDK 原生数值，直接转 Decimal（AGENTS.md §3）。
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from finsage.exceptions import NormalizationError, ProviderBadResponseError, ProviderError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .normalize import normalize_metric, normalize_period, normalize_unit

# 一次行情查询仅拉最近 ~400 天，控制流量与耗时。
_FETCH_SPAN_DAYS = 400

_PERIOD_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_PERIOD_Q = re.compile(r"(\d{4})[Qq]([1-4])")
_PERIOD_YEAR = re.compile(r"(\d{4})")

# Baostock 的 login/logout 是**进程级全局会话**（不是每请求连接）：并发调用时
# 任一请求的 logout() 会关掉其它请求正在用的会话（审计 §2.7）。故串行化整段
# login → query → logout。锁在进程内生效（to_thread 共用同一进程）。
_BS_SESSION_LOCK = threading.Lock()

# Baostock query_profit_data 字段 -> (规范指标名, 单位)。
# 【SDK 字段待实测校准】MBRevenue/netProfit 的具体单位与口径需实测确认。
_PROFIT_METRICS = (
    ("MBRevenue", "revenue", "CNY_m"),
    ("netProfit", "net_income", "CNY_wan"),
    ("epsTTM", "eps", "share"),
)
_PROFIT_PCT_METRICS = (
    ("gpMargin", "gross_margin", "pct"),
    ("npMargin", "net_income_margin", "pct"),
)


class BaoStockProvider(BaseProvider):
    """A 股行情/财务/公司概况数据源（Baostock）。

    - ``name`` = ``baostock``，``capability_prefix`` = ``baostock``；
    - 仅支持 A 股市场（CN.SH / CN.SZ / CN）；
    - 无新闻接口，``get_news`` 返回空列表（诚实声明，不虚拟数据）。
    """

    name = "baostock"
    capability_prefix = "baostock"

    # ------------------------------------------------------------------
    # SDK 交互骨架
    # ------------------------------------------------------------------
    def _query(self, op: str, fn: Callable[[Any], Any]) -> list[dict[str, str]]:
        """登录 -> 调用 Baostock 查询 -> 登出，返回行数据列表（同步，供 to_thread）。

        并发安全（审计 §2.7）：整段会话由 ``_BS_SESSION_LOCK`` 串行化。
        Baostock 的 login/logout 是进程级全局会话，不串行化时并发请求会互相
        把对方的会话关掉。
        """
        import baostock as bs  # 延迟 import

        with _BS_SESSION_LOCK:
            login = bs.login()
            if login.error_code != "0":
                raise ProviderError(f"{self.name} login failed: {login.error_msg}")
            try:
                rs = fn(bs)
                if rs.error_code != "0":
                    raise ProviderError(
                        f"{self.name} {op} failed: {rs.error_code} {rs.error_msg}"
                    )
                # Baostock 行数据为列值列表；列名在 rs.fields 中，按位置配对成 dict。
                fields = list(rs.fields)
                return [dict(zip(fields, row, strict=False)) for row in (rs.data or [])]
            finally:
                bs.logout()

    @staticmethod
    def _baostock_code(symbol: str, market: str) -> str:
        """symbol+market -> ``sh.600000``/``sz.000001``。

        市场以 SH 结尾或含 SHANGHAI -> 上交所；SZ 结尾 -> 深交所；
        市场无法区分（如 CN）时按代码前缀推断：6 开头视为上交所。
        """
        m = market.upper()
        if m.endswith("SH") or "SHANGHAI" in m:
            return f"sh.{symbol}"
        if m.endswith("SZ"):
            return f"sz.{symbol}"
        prefix = "sh" if symbol.startswith("6") else "sz"
        return f"{prefix}.{symbol}"

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        """Baostock 返回字符串或空串；非法 / NaN / ±Inf 返回 None 以便调用方跳过。

        审计 §2.6：此前只挡 ``nan/NaN``，``inf/Infinity`` 可进入下游确定性计算。
        """
        if value is None:
            return None
        s = str(value).strip()
        if not s or s in ("", "None"):
            return None
        try:
            d = Decimal(s)
        except InvalidOperation:
            # 非 Decimal 字面量（如 "nan"/"inf"/"Infinity"）走 float 判定。
            try:
                f = float(s)
            except ValueError:
                return None
            if math.isnan(f) or math.isinf(f):
                return None
            return None
        # Decimal("NaN") / Decimal("Infinity") 合法构造但不可参与算术。
        if d.is_nan() or d.is_infinite():
            return None
        return d

    @classmethod
    def _parse_period(cls, period: str) -> tuple[int, int]:
        """解析报告期为 (year, quarter)。支持 ``2024`` / ``2024Q2`` / ``2024-12-31``。"""
        s = period.strip()
        m = _PERIOD_DATE.fullmatch(s)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            return year, (month - 1) // 3 + 1
        m = _PERIOD_Q.fullmatch(s)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = _PERIOD_YEAR.fullmatch(s)
        if m:
            return int(m.group(1)), 4
        raise NormalizationError(f"unsupported financial period: {period!r}")

    @staticmethod
    def _period_type(stat_date: str | None) -> str:
        """按 statDate 月末推断 period_type（FY 或 Q1..Q4）。"""
        if not stat_date:
            return "FY"
        m = _PERIOD_DATE.fullmatch(stat_date.strip())
        if not m:
            return "FY"
        month = int(m.group(2))
        return {3: "Q1", 6: "Q2", 9: "Q3", 12: "FY"}.get(month, "FY")

    @staticmethod
    def _norm_market(market: str) -> str:
        """将调用方市场归一化为 CN.SH / CN.SZ。"""
        m = market.upper()
        if m.endswith("SH") or "SHANGHAI" in m:
            return "CN.SH"
        if m.endswith("SZ"):
            return "CN.SZ"
        return "CN"

    # ------------------------------------------------------------------
    # FinancialDataProvider 契约实现
    # ------------------------------------------------------------------
    async def get_quote(self, symbol: str, market: str) -> Quote:
        """最新 A 股报价（取最近交易日 close 作为示例价格）。

        【SDK 字段待实测校准】行情字段按 query_history_k_data_plus 官方示例映射。
        """
        ensure_symbol_market(symbol, market)
        code = self._baostock_code(symbol, market)
        rows = await self._call("query_history", asyncio.to_thread(self._fetch_quote, code))
        if not rows:
            raise ProviderBadResponseError(f"{self.name} no quote rows for {code}")
        last = rows[-1]
        price = self._to_decimal(last.get("close")) or self._to_decimal(last.get("preclose"))
        if price is None:
            raise ProviderBadResponseError(f"{self.name} quote price unavailable for {code}")
        name = await self._fetch_name(code)
        return Quote(
            symbol=symbol,
            market=self._norm_market(market),
            name=name,
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """指定报告期财务指标。

        由 query_profit_data 提取营收/净利润/EPS/毛利率等字段；无法定位的行跳过。
        【SDK 字段待实测校准】营收与净利润的单位与口径待实测确认。
        """
        ensure_symbol_market(symbol, market)
        code = self._baostock_code(symbol, market)
        year, quarter = self._parse_period(period)
        rows = await self._call(
            "query_profit_data",
            asyncio.to_thread(
                self._query,
                "query_profit_data",
                lambda bs: bs.query_profit_data(code=code, year=year, quarter=quarter),
            ),
        )
        now = utcnow()
        metrics: list[FinancialMetric] = []
        for row in rows:
            stat_date = row.get("statDate")
            period_label = normalize_period(stat_date or f"{year}Q{quarter}")
            period_type = self._period_type(stat_date)
            for field, metric, unit in _PROFIT_METRICS:
                value = self._to_decimal(row.get(field))
                if value is None:
                    continue
                metrics.append(
                    self._metric(symbol, market, metric, value, unit,
                                 period_label, period_type, now)
                )
            for field, metric, unit in _PROFIT_PCT_METRICS:
                value = self._to_decimal(row.get(field))
                if value is None:
                    continue
                metrics.append(
                    self._metric(symbol, market, metric, value, unit,
                                 period_label, period_type, now)
                )
        return metrics

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """公司概况：名称、行业、交易所（来自 stock_basic / stock_industry）。"""
        ensure_symbol_market(symbol, market)
        code = self._baostock_code(symbol, market)
        basic = await self._call(
            "query_stock_basic",
            asyncio.to_thread(
                self._query,
                "query_stock_basic",
                lambda bs: bs.query_stock_basic(code=code),
            ),
        )
        industry_rows = await self._call(
            "query_stock_industry",
            asyncio.to_thread(
                self._query,
                "query_stock_industry",
                lambda bs: bs.query_stock_industry(code=code),
            ),
        )
        if not basic:
            raise ProviderBadResponseError(f"{self.name} no profile for {code}")
        row = basic[0]
        exchange = "上海证券交易所" if code.startswith("sh.") else "深圳证券交易所"
        industry = industry_rows[0].get("industry") if industry_rows else None
        return CompanyProfile(
            symbol=symbol,
            market=self._norm_market(market),
            name=row.get("code_name") or symbol,
            currency="CNY",
            sector=None,
            industry=industry,
            description=None,
            website=None,
            country="CN",
            exchange=exchange,
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """公司新闻。

        Baostock 不提供新闻接口，诚实返回空列表（不虚构数据，AGENTS.md §10）。
        """
        return []

    async def health_check(self) -> ProviderHealth:
        """以一次登录/登出判定健康；失败经 SDK 异常映射抛出。"""
        ok = await self._call("login", asyncio.to_thread(self._ping))
        capability = self._capability(self.name)
        now = utcnow()
        if ok:
            return ProviderHealth(
                provider_name=self.name,
                capability=capability,
                status="healthy",
                success_rate=Decimal("1.000000"),
                last_success_at=now,
                updated_at=now,
            )
        return ProviderHealth(
            provider_name=self.name,
            capability=capability,
            status="degraded",
            success_rate=Decimal("0.000000"),
            last_failure_at=now,
            failure_count=1,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # 内部同步辅助
    # ------------------------------------------------------------------
    async def _fetch_name(self, code: str) -> str | None:
        basic = await self._call(
            "query_stock_basic",
            asyncio.to_thread(
                self._query,
                "query_stock_basic",
                lambda bs: bs.query_stock_basic(code=code),
            ),
        )
        return basic[0].get("code_name") if basic else None

    def _fetch_quote(self, code: str) -> list[dict[str, str]]:
        today = datetime.now(UTC).date()
        start = (today - timedelta(days=_FETCH_SPAN_DAYS)).isoformat()
        return self._query(
            "query_history_k_data_plus",
            lambda bs: bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,preclose,volume,pctChg,peTTM,pbMRQ",
                start_date=start,
                end_date=str(today),
                frequency="d",
                adjustflag="3",
            ),
        )

    @staticmethod
    def _ping() -> bool:
        import baostock as bs  # 延迟 import

        login = bs.login()
        try:
            return login.error_code == "0"
        finally:
            bs.logout()

    def _metric(self, symbol: str, market: str, metric: str, value: Decimal,
                unit: str, period: str, period_type: str, now: datetime) -> FinancialMetric:
        return FinancialMetric(
            company="",  # 财务接口不含公司名，交由上层补全
            ticker=symbol,
            market=self._norm_market(market),
            metric=normalize_metric(metric),
            value=value,
            currency="CNY",
            unit=normalize_unit(unit),
            period=period,
            period_type=period_type,
            source=self.name,
            retrieved_at=now,
        )


__all__ = ["BaoStockProvider"]

