"""TushareProvider —— 付费/注册制数据源（预留接入，opt-in 需 token）。

数据源：Tushare（http://tushare.pro），需注册账号并申请 token（规格 §2 明确 Tushare
为可选 opt-in 数据源）。本 Provider 实现 FinancialDataProvider 契约，但不伪造实现；
token 缺失/未配置时，所有契约方法按 ProviderBadResponseError 干净失败，生产接入时
填入 token 即可启用。

诚实标注：Tushare 官方 SDK 需要在注册后申请具体接口权限；以下契约方法按 Tushare
标准 pro API（ts.pro_api(token)）编写，字段映射基于常见返回命名并标注『SDK 字段
待实测校准』，落地前需以真实 token + 接口权限校准（AGENTS.md §10）。

对外访问合规：Tushare 为注册制正规数据服务，有明确 ToS 与频控，接入即遵守其
许可条款；本模块只做时间窗内单次/低频调用。
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from finsage.exceptions import ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .normalize import normalize_market

logger = logging.getLogger(__name__)

# Tushare 财务指标 -> 规范指标名（对应 pro 接口列名）。【SDK 字段待实测校准】
_FINANCIAL_COLUMNS: dict[str, str] = {
    "revenue": "revenue",
    "n_income": "net_income",
    "total_assets": "total_assets",
    "total_liab": "total_liabilities",
    "compound_roe": "roe",
}


class TushareProvider(BaseProvider):
    """基于 Tushare pro API 的提供者（opt-in 需 token，规格 §2）。

    ``name="tushare"``。token 通过 ``token`` 构造参数注入（一般来自 Settings），
    未配置时契约调用按 ProviderBadResponseError 干净失败。
    """

    name = "tushare"
    capability_prefix = "tushare"

    def __init__(self, *, token: str | None = None, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self._token = token

    def _require_token(self) -> str:
        if not self._token:
            raise ProviderBadResponseError(
                "tushare.token not configured; 需在 tushare.pro 注册并设置 FIN_TUSHARE_TOKEN"
            )
        return self._token

    @staticmethod
    def _load_sdk() -> Any:
        try:
            import tushare as ts  # noqa: PLC0415 - 延迟 import
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise ProviderBadResponseError("tushare SDK is not installed") from exc
        if not hasattr(ts, "pro_api"):
            raise ProviderBadResponseError("tushare SDK missing pro_api")
        return ts

    def _pro(self) -> Any:
        token = self._require_token()
        sdk = self._load_sdk()
        return sdk.pro_api(token)

    def _cn_code(self, symbol: str) -> str:
        digits = "".join(ch for ch in str(symbol) if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else digits or str(symbol)

    # ---------- 契约实现 ----------

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """实时行情：基于 ``pro.ask("realtime_quote", ts_code=...)``。"""
        ensure_symbol_market(symbol, market)
        self._pro()  # 校验 token/SDK 就绪，缺失干净失败【SDK 字段待实测校准】
        code = self._cn_code(symbol)
        suffix = "SH" if code.startswith(("6", "5", "9")) else "SZ"
        ts_code = f"{code}.{suffix}"

        def _fetch() -> Any:
            pro = self._pro()

            def _inner() -> Any:
                return pro.ask("realtime_quote", ts_code=ts_code)

            # 部分 pro 版本超时参数写法不同，按 SDK 版本兼容
            try:
                return pro.ts_realtime_quote(ts_code=ts_code)
            except AttributeError:
                return _inner()

        data = await self._call("quote", asyncio.to_thread(_fetch))
        # 【SDK 字段待实测校准】realtime_quote 返回 DataFrame，取第一行最新价。
        # 后处理异常保护（审计 §2.5）：响应结构非预期时转 ProviderBadResponseError，
        # 进入 failover 链而非打穿降级链。
        rows = self._guard_parse("quote", lambda: _rows_from_payload(data))
        if not rows:
            raise ProviderBadResponseError(f"{self.name}.quote: no data for {ts_code}")
        row = rows[0]

        def _num(key: str) -> Decimal | None:
            try:
                return Decimal(str(row.get(key)))
            except (TypeError, ValueError, ArithmeticError):
                return None

        price = self._guard_parse(
            "quote", lambda: _num("price") or _num("pre_close") or _num("close")
        )
        if price is None:
            raise ProviderBadResponseError(f"{self.name}.quote: missing price for {ts_code}")
        return Quote(
            symbol=symbol,
            market=normalize_market(market),
            name=str(row.get("name") or symbol),
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """资产负债表 + 财务指标。"""
        ensure_symbol_market(symbol, market)
        self._pro()
        code = self._cn_code(symbol)
        suffix = "SH" if code.startswith(("6", "5", "9")) else "SZ"
        ts_code = f"{code}.{suffix}"
        period_str = period if "-" not in period else period[:7]

        def _fetch() -> Any:
            pro = self._pro()
            return pro.fina_indicator(ts_code=ts_code, period=period_str, limit=1)

        frame = await self._call("financials", asyncio.to_thread(_fetch))
        rows = frame.to_dict("records") if hasattr(frame, "to_dict") else (frame or [])
        if not rows:
            return []
        row = rows[0]
        norm_market = normalize_market(market)
        retrieved = utcnow()
        metrics: list[FinancialMetric] = []
        for sdk_key, metric in _FINANCIAL_COLUMNS.items():
            value = row.get(sdk_key)
            if value is None:
                continue
            metrics.append(
                FinancialMetric(
                    company=str(row.get("ts_code") or symbol),
                    ticker=symbol,
                    market=norm_market,
                    metric=metric,
                    value=Decimal(str(value)),
                    currency="CNY",
                    unit=None if metric in ("roe",) else "CNY_yi",
                    period=period,
                    period_type="FY",
                    source=self.name,
                    retrieved_at=retrieved,
                )
            )
        return metrics

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """公司基本信息：基于 ``pro.stock_basic``。"""
        ensure_symbol_market(symbol, market)
        self._pro()
        code = self._cn_code(symbol)
        suffix = "SH" if code.startswith(("6", "5", "9")) else "SZ"
        ts_code = f"{code}.{suffix}"

        def _fetch() -> Any:
            pro = self._pro()
            return pro.stock_basic(ts_code=ts_code, fields="ts_code,name,industry,area")

        frame = await self._call("company_profile", asyncio.to_thread(_fetch))
        rows = frame.to_dict("records") if hasattr(frame, "to_dict") else (frame or [])
        if not rows:
            raise ProviderBadResponseError(
                f"{self.name}.company_profile: no data for {ts_code}"
            )
        row = rows[0]
        return CompanyProfile(
            symbol=symbol,
            market=normalize_market(market),
            name=str(row.get("name") or symbol),
            currency="CNY",
            industry=row.get("industry"),
            country="CN",
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """Tushare 标准 pro 未直接提供单标的新闻流，返回空列表（不支持该能力）。"""
        ensure_symbol_market(symbol, market)
        return []

    async def health_check(self) -> ProviderHealth:
        """健康检查：token/SDK 就绪即标记 healthy；缺失归 down。"""
        capability = self._capability("quote")
        now = utcnow()
        try:
            self._pro()
        except Exception as exc:  # noqa: BLE001 - 未配置/ SDK 缺失统一归 down
            logger.warning("tushare_health_failed", extra={"extra": {"error": type(exc).__name__}})
            return ProviderHealth(
                provider_name=self.name,
                capability=capability,
                status="down",
                success_rate=Decimal("0.0"),
                last_failure_at=now,
                failure_count=1,
                updated_at=now,
            )
        return ProviderHealth(
            provider_name=self.name,
            capability=capability,
            status="healthy",
            success_rate=Decimal("1.0"),
            last_success_at=now,
            failure_count=0,
            updated_at=now,
        )


def _rows_from_payload(data: Any) -> list[Any]:
    """把 realtime_quote 的响应归一成行列表（DataFrame 或原生 list 均可）。"""
    if hasattr(data, "to_dict"):
        return list(data.to_dict("records"))
    return list(data or [])


__all__ = ["TushareProvider"]