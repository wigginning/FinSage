"""Companies API 服务层（ADR-0006，Proposed）。

数据装配规则（诚实，不伪造）：
- 公司列表来源：聚合自 ``TaskManager`` 中 research 类任务的去重 (ticker, market)；
  无任务时返回空列表（不返回演示占位公司）。
- 档案/行情/财务：经 ``ProviderRegistry``（AGENTS.md §4，绝不直触 SDK）best-effort 增强；
  Provider 未装配或调用失败时对应字段诚实为 null/空，绝不伪造数字。
- 研究次数/最近研究：聚合自任务。

``registry`` 可注入便于测试；默认 None 表示未装配（诚实空增强）。
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from finsage.api.schemas import (
    CompanyDetail,
    CompanyListResponse,
    CompanySummary,
    FinancialMetricSummary,
    TaskStatus,
    TaskSummary,
)
from finsage.api.tasks import TaskManager

# 聚合时一次取回的最大任务数（内存态，足够覆盖演示/测试规模）。
_AGGREGATE_LIMIT = 1000
# 增强结果 MRU 缓存容量（§3.1：避免重复 provider 调用）。
_ENRICH_CACHE_MAX = 64
# 单次增强（profile/quote）的短超时上界（§3.1：akshare→baostock failover 可达 ~20s）。
_ENRICH_TIMEOUT = 5.0


class CompanyService:
    """公司列表/详情聚合服务。"""

    def __init__(self, task_manager: TaskManager, registry: Any | None = None) -> None:
        self._tasks = task_manager
        self._registry = registry
        self._enrich_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._financials_cache: OrderedDict[tuple[str, str], list[FinancialMetricSummary]] = (
            OrderedDict()
        )

    # ---- 内部聚合 ----

    def _aggregate(self) -> list[dict[str, Any]]:
        """从 research 任务聚合去重公司（ticker, market）。"""
        companies: dict[tuple[str, str], dict[str, Any]] = {}
        for t in self._tasks.list(kind="research", limit=_AGGREGATE_LIMIT):
            if not t.ticker:
                continue
            market = t.market or "CN"
            key = (t.ticker, market)
            entry = companies.setdefault(
                key,
                {
                    "ticker": t.ticker,
                    "name": t.company or t.ticker,
                    "market": market,
                    "research_count": 0,
                    "last_researched_at": None,
                },
            )
            entry["research_count"] += 1
            if entry["last_researched_at"] is None or t.created_at > entry["last_researched_at"]:
                entry["last_researched_at"] = t.created_at
        return list(companies.values())

    async def _enrich(self, entry: dict[str, Any]) -> dict[str, Any]:
        """best-effort 用 Provider Registry 增强档案/行情；失败诚实降级。

        MRU 缓存（§3.1）：同一 (ticker, market) 的增强结果复用，避免重复 provider 调用。
        """
        key = (entry["ticker"], entry["market"])
        cached = self._enrich_cache.get(key)
        if cached is not None:
            self._enrich_cache.move_to_end(key)
            return dict(cached)
        enriched = await self._enrich_uncached(entry)
        self._enrich_cache[key] = enriched
        self._enrich_cache.move_to_end(key)
        if len(self._enrich_cache) > _ENRICH_CACHE_MAX:
            self._enrich_cache.popitem(last=False)
        return enriched

    async def _enrich_uncached(self, entry: dict[str, Any]) -> dict[str, Any]:
        """无缓存的增强实现（并发调用 profile + quote）。"""
        if self._registry is None:
            return entry
        try:
            profile = await asyncio.wait_for(
                self._registry.invoke(
                    lambda p: p.get_company_profile(entry["ticker"], entry["market"]),
                    operation="company_profile",
                    market=entry["market"],
                ),
                timeout=_ENRICH_TIMEOUT,
            )
            entry["name"] = profile.name or entry["name"]
            entry["industry"] = profile.industry
            entry["currency"] = profile.currency
            entry["sector"] = profile.sector
            entry["description"] = profile.description
            entry["website"] = profile.website
            entry["country"] = profile.country
            entry["exchange"] = profile.exchange
            entry["source"] = profile.source
            entry["retrieved_at"] = (
                profile.retrieved_at.isoformat() if profile.retrieved_at else None
            )
        except Exception:  # noqa: BLE001 —— Provider 失败诚实降级，不击穿列表
            pass
        try:
            quote = await asyncio.wait_for(
                self._registry.invoke(
                    lambda p: p.get_quote(entry["ticker"], entry["market"]),
                    operation="quote",
                    market=entry["market"],
                ),
                timeout=_ENRICH_TIMEOUT,
            )
            entry["price"] = quote.price
            entry["currency"] = quote.currency
        except Exception:  # noqa: BLE001
            pass
        return entry

    def _to_summary(self, entry: dict[str, Any]) -> CompanySummary:
        return CompanySummary(
            ticker=entry["ticker"],
            name=entry.get("name") or entry["ticker"],
            market=entry["market"],
            industry=entry.get("industry"),
            currency=entry.get("currency"),
            price=entry.get("price"),
            change_pct=entry.get("change_pct"),
            research_count=entry.get("research_count", 0),
            last_researched_at=entry.get("last_researched_at"),
            source=entry.get("source"),
            retrieved_at=entry.get("retrieved_at"),
        )

    # ---- 对外接口 ----

    def count(self, *, market: str | None = None) -> int:
        """公司总数（仅聚合，不做 Provider 增强）。

        供 /stats 等只取计数的场景，避免无谓的行情/档案增强（akshare→baostock
        failover 可达 ~20s）。
        """
        entries = self._aggregate()
        if market:
            entries = [e for e in entries if e["market"] == market]
        return len(entries)

    async def list(
        self,
        *,
        market: str | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
        enrich: bool = True,
    ) -> CompanyListResponse:
        """列出公司：聚合 + 增强 + 过滤 + 分页。

        ``enrich=False`` 时跳过 Provider 增强（§3.1 deferred enrichment）：
        仅返回聚合的基础数据（秒回），供前端先出骨架、行情/行业异步补。
        """
        entries = self._aggregate()
        if enrich:
            entries = await asyncio.gather(*[self._enrich(e) for e in entries])
        if market:
            entries = [e for e in entries if e["market"] == market]
        if keyword:
            kw = keyword.strip().lower()
            entries = [
                e
                for e in entries
                if kw in e["ticker"].lower() or kw in (e.get("name") or "").lower()
            ]
        entries.sort(key=lambda e: e.get("last_researched_at") or "", reverse=True)
        total = len(entries)
        page = entries[offset : offset + max(0, limit)]
        return CompanyListResponse(
            items=[self._to_summary(e) for e in page],
            total=total,
        )

    async def get(self, ticker: str, market: str | None = None) -> CompanyDetail | None:
        """按 ticker 取公司详情；不存在返回 None（路由据此 404）。"""
        entries = await asyncio.gather(*[self._enrich(e) for e in self._aggregate()])
        match = next(
            (
                e
                for e in entries
                if e["ticker"] == ticker and (market is None or e["market"] == market)
            ),
            None,
        )
        if match is None:
            return None

        financials: list[FinancialMetricSummary] = []
        if self._registry is not None:
            fkey = (match["ticker"], match["market"])
            cached_fin = self._financials_cache.get(fkey)
            if cached_fin is not None:
                self._financials_cache.move_to_end(fkey)
                financials = list(cached_fin)
            else:
                try:
                    metrics = await self._registry.invoke(
                        lambda p: p.get_financials(match["ticker"], match["market"], "FY"),
                        operation="financials",
                        market=match["market"],
                    )
                    financials = [
                        FinancialMetricSummary(
                            metric=m.metric,
                            value=str(m.value),
                            period=m.period,
                            unit=m.unit,
                            currency=m.currency,
                            source=m.source,
                        )
                        for m in metrics
                    ]
                    self._financials_cache[fkey] = financials
                    self._financials_cache.move_to_end(fkey)
                    if len(self._financials_cache) > _ENRICH_CACHE_MAX:
                        self._financials_cache.popitem(last=False)
                except Exception:  # noqa: BLE001
                    financials = []

        recent = self._tasks.list(kind="research", limit=10)
        recent = [t for t in recent if t.ticker == ticker]
        recent_tasks = [
            TaskSummary(
                task_id=t.task_id,
                kind=t.kind,
                status=TaskStatus(t.status),
                progress=t.progress,
                trace_id=t.trace_id,
                created_at=t.created_at,
                error_code=t.error_code,
                query=t.query,
                company=t.company,
                ticker=t.ticker,
            )
            for t in recent
        ]

        return CompanyDetail(
            **self._to_summary(match).model_dump(),
            sector=match.get("sector"),
            description=match.get("description"),
            website=match.get("website"),
            country=match.get("country"),
            exchange=match.get("exchange"),
            financials=financials,
            recent_tasks=recent_tasks,
        )


__all__ = ["CompanyService"]
