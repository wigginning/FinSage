"""TencentQuoteProvider（A 股行情，公开低频 HTTP 源）。

数据源：腾讯公开行情接口 ``https://qt.gtimg.cn/q=<code>``（无 SDK、无 token）。
仅作高频受限下的开发/测试连通源，遵循反爬合规：低频、带 Referer 与 UA、
单次/少量请求，不批量抓取；生产高并发数据源应走付费源（见 Tushare 预留）。

实现说明：
- 非 SDK 源，基于 httpx；仍经 ``BaseProvider._call`` 在 ``self.timeout`` 窗口内执行，
  超时/失败映射 ProviderTimeoutError / ProviderBadResponseError；
- 返回体形如 ``v_sz000001="1~平安银行~000001~11.41~..."``，按 ``~`` 切分，
  字段下标依赖腾讯接口稳定约定，下标以便于维护的命名常量承接（字段名/下标
  以真实样本校准，见 C-10 冒烟记录）；
- 仅覆盖行情（get_quote + health_check），基本面/新闻该源不提供：
  financials/news 返回空列表，company_profile 返回仅名称的最小化对象。

合规边界：对外部站点只做低频请求，不绕过任何访问控制、不发送伪造来源掩盖身份。
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from decimal import Decimal
from typing import Any

import httpx

from finsage.exceptions import ProviderBadResponseError

from .base import BaseProvider, ensure_symbol_market, utcnow
from .domain import CompanyProfile, FinancialMetric, NewsItem, ProviderHealth, Quote
from .normalize import normalize_market

logger = logging.getLogger(__name__)

_API = "https://qt.gtimg.cn/q={code}"
_REFERER = "https://gu.qq.com/"
_UA = "Mozilla/5.0 (compatible; FinSage/0.1; research-client)"

# 腾讯行情响应字段下标（按 `~` 切分后的约定）。
# 【字段下标待实测校准】下标按腾讯接口常见输出编写，C-10 冒烟以真实样本校准。
_IDX_NAME = 1        # 名称
_IDX_CODE = 2        # 代码
_IDX_PRICE = 3       # 最新价
_IDX_PREV_CLOSE = 4  # 昨收
_IDX_CHANGE_PCT = 32 # 涨跌幅(%)
_IDX_HIGH = 33       # 最高
_IDX_LOW = 34        # 最低

_PAYLOAD_RE = re.compile(r'"[^"]*"')


def _cn_request_code(symbol: str, market: str) -> str:
    """按市场生成腾讯请求前缀代码（sh/sz），容忍带前缀写法。"""
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())
    code = digits[-6:] if len(digits) >= 6 else digits or str(symbol)
    m = normalize_market(market)
    if m == "CN.SH":
        return f"sh{code}"
    if m == "CN.SZ":
        return f"sz{code}"
    # CN 兜底：6/5/9 开头归沪，其余归深（北交所拦截，避免臆断）。
    return f"{'sh' if code.startswith(('6', '5', '9')) else 'sz'}{code}"


def _to_decimal(value: Any) -> Decimal | None:
    """转 Decimal；非法 / NaN / Infinity 一律返回 None。

    审计 §2.6：NaN/Inf 曾可进入 Quote.price 并污染下游确定性金融计算。
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return Decimal(str(num))


class TencentQuoteProvider(BaseProvider):
    """基于腾讯公开行情接口的 A 股行情 Provider（C-10 真实连通源）。"""

    name = "tencent"
    capability_prefix = "tencent"

    # ---------- SDK 访问骨架（HTTP） ----------

    async def _fetch_quote(self, code: str) -> list[str]:
        """执行单次行情请求并解析为字段切片。"""

        def _request() -> list[str]:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    _API.format(code=code),
                    headers={"Referer": _REFERER, "User-Agent": _UA},
                )
                resp.raise_for_status()
            m = _PAYLOAD_RE.search(resp.text)
            if not m:
                raise ProviderBadResponseError(
                    f"{self.name}.quote: unparseable payload for {code}"
                )
            return m.group(0)[1:-1].split("~")

        return await self._call("quote", asyncio.to_thread(_request))

    # ---------- 契约实现 ----------

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """实时行情（§4.7）。"""
        ensure_symbol_market(symbol, market)
        code = _cn_request_code(symbol, market)
        fields = await self._fetch_quote(code)
        if len(fields) <= _IDX_PRICE:
            raise ProviderBadResponseError(f"{self.name}.quote: short payload for {symbol}")
        price = _to_decimal(fields[_IDX_PRICE])
        if price is None:
            raise ProviderBadResponseError(f"{self.name}.quote: missing price for {symbol}")
        return Quote(
            symbol=symbol,
            market=normalize_market(market),
            name=fields[_IDX_NAME].strip() or None,
            price=price,
            currency="CNY",
            timestamp=utcnow(),
            source=self.name,
        )

    async def get_financials(self, symbol: str, market: str, period: str) -> list[FinancialMetric]:
        """Tencent 公开行情源不提供结构化基本面，返回空列表（不支持该能力）。"""
        ensure_symbol_market(symbol, market)
        return []

    async def get_company_profile(self, symbol: str, market: str) -> CompanyProfile:
        """最小化公司对象：仅名称可靠，字段按『SDK 字段待实测校准』留空。"""
        ensure_symbol_market(symbol, market)
        code = _cn_request_code(symbol, market)
        fields = await self._fetch_quote(code)
        name = fields[_IDX_NAME].strip() if len(fields) > _IDX_NAME else ""
        return CompanyProfile(
            symbol=symbol,
            market=normalize_market(market),
            name=name or symbol,
            currency="CNY",
            country="CN",
            exchange=normalize_market(market),
            source=self.name,
            retrieved_at=utcnow(),
        )

    async def get_news(self, symbol: str, market: str, limit: int = 20) -> list[NewsItem]:
        """Tencent 公开行情源不提供新闻流，返回空列表（不支持该能力）。"""
        ensure_symbol_market(symbol, market)
        return []

    async def health_check(self) -> ProviderHealth:
        """健康检查：以一次最小行情探活标记状态。"""
        capability = self._capability("quote")
        updated = utcnow()
        try:
            await self.get_quote("000001", "CN.SZ")
        except Exception as exc:  # noqa: BLE001 - 探活失败统一归 down
            logger.warning("tencent_health_failed", extra={"extra": {"error": type(exc).__name__}})
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


__all__ = ["TencentQuoteProvider"]