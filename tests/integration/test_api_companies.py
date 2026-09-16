"""Companies API 集成测试（ADR-0006，Proposed）。

- GET /api/v1/companies：从 research 任务聚合去重公司 + 分页/过滤；
- GET /api/v1/companies/{ticker}：详情（档案/财务/近期任务）；不存在 → FIN-1004；
- 无任务时返回空列表（不返回演示占位公司）；
- Provider Registry 增强 best-effort：失败诚实降级，不伪造数字；
- 新端点继承 router 级 require_auth（缺 token → FIN-1002）。

不依赖真实 DB / Milvus / 模型：注入替身 runner、内存存储与 fake registry。
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app
from finsage.api.companies import CompanyService
from finsage.api.tasks import TaskManager
from finsage.providers.finance.domain import CompanyProfile, FinancialMetric, Quote
from finsage.settings import Settings


class FakeRunner:
    """成功替身：产出一组事件并完成。"""

    def __init__(self, audit: AuditStore) -> None:
        self.audit = audit

    async def run(self, kind: str, *, input_, handle) -> None:
        handle.emit("workflow.stage", {"name": "parse", "status": "ok"})
        self.audit.add(handle.trace_id, {"stage": "workflow", "kind": kind, "status": "ok"})
        handle.result = {"answer": "ok", "kind": kind}


class FakeRegistry:
    """fake Provider Registry：返回固定档案/行情/财务，验证增强路径。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def invoke(self, factory, *, operation: str, market: str):
        if self.fail:
            raise RuntimeError("provider down")
        if operation == "company_profile":
            return CompanyProfile(
                symbol="300750.SZ",
                market="CN",
                name="宁德时代",
                currency="CNY",
                sector="电池",
                industry="动力电池",
                description="动力电池龙头",
                website="https://www.catl.com",
                country="CN",
                exchange="深圳证券交易所",
                source="fake",
                retrieved_at=datetime(2026, 8, 24, tzinfo=UTC),
            )
        if operation == "quote":
            return Quote(
                symbol="300750.SZ",
                market="CN",
                name="宁德时代",
                price=Decimal("184.20"),
                currency="CNY",
                timestamp=datetime(2026, 8, 24, tzinfo=UTC),
                source="fake",
            )
        if operation == "financials":
            return [
                FinancialMetric(
                    company="宁德时代",
                    ticker="300750.SZ",
                    market="CN",
                    metric="revenue",
                    value=Decimal("362060000000"),
                    currency="CNY",
                    unit="CNY",
                    period="2024",
                    period_type="FY",
                    source="fake",
                    retrieved_at=datetime(2026, 8, 24, tzinfo=UTC),
                )
            ]
        return []


def _app(api_token: str = "", registry=None):
    audit = AuditStore()
    task_manager = TaskManager()
    deps = Deps(
        settings=Settings(api_token=api_token),
        task_manager=task_manager,
        runner=FakeRunner(audit),
        files=FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
        companies=CompanyService(task_manager=task_manager, registry=registry),
    )
    return create_app(settings=Settings(api_token=api_token), deps=deps)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _submit_research(client: httpx.AsyncClient, **overrides) -> str:
    payload = {"query": "q", "market": "CN", **overrides}
    resp = await client.post("/api/v1/research", json=payload)
    assert resp.status_code == 200
    return resp.json()["task_id"]


async def test_companies_empty_when_no_tasks():
    """无 research 任务时返回空列表（不返回演示占位公司）。"""
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/companies")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


async def test_companies_aggregates_from_tasks():
    """从 research 任务聚合去重公司，并统计研究次数/最近研究。"""
    async with _client(_app()) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await _submit_research(c, company="腾讯控股", ticker="0700", market="HK")
        await asyncio.sleep(0.05)
        resp = await c.get("/api/v1/companies")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        by_ticker = {i["ticker"]: i for i in body["items"]}
        assert by_ticker["300750.SZ"]["research_count"] == 2
        assert by_ticker["300750.SZ"]["name"] == "宁德时代"
        assert by_ticker["0700"]["market"] == "HK"


async def test_companies_filter_and_pagination():
    async with _client(_app()) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await _submit_research(c, company="腾讯控股", ticker="0700", market="HK")
        await asyncio.sleep(0.05)
        by_market = await c.get("/api/v1/companies", params={"market": "HK"})
        assert by_market.status_code == 200
        assert by_market.json()["total"] == 1
        assert by_market.json()["items"][0]["ticker"] == "0700"

        kw = await c.get("/api/v1/companies", params={"keyword": "宁德"})
        assert kw.status_code == 200
        assert kw.json()["total"] == 1
        assert kw.json()["items"][0]["ticker"] == "300750.SZ"

        page = await c.get("/api/v1/companies", params={"limit": 1})
        assert page.status_code == 200
        assert len(page.json()["items"]) == 1
        assert page.json()["total"] == 2


async def test_company_detail_enriched_from_registry():
    """详情经 Provider Registry 增强档案/行情/财务，并附近期任务。"""
    async with _client(_app(registry=FakeRegistry())) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await asyncio.sleep(0.05)
        resp = await c.get("/api/v1/companies/300750.SZ")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "宁德时代"
        assert body["industry"] == "动力电池"
        assert body["price"] == "184.20"
        assert body["currency"] == "CNY"
        assert body["source"] == "fake"
        assert body["financials"], "应返回财务指标"
        assert body["financials"][0]["metric"] == "revenue"
        assert body["recent_tasks"], "应返回近期任务"
        assert body["recent_tasks"][0]["ticker"] == "300750.SZ"


async def test_company_detail_degrades_when_registry_fails():
    """Provider 失败时诚实降级：档案/行情/财务为空，不伪造数字。"""
    async with _client(_app(registry=FakeRegistry(fail=True))) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await asyncio.sleep(0.05)
        resp = await c.get("/api/v1/companies/300750.SZ")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "宁德时代"  # 来自任务聚合，非 Provider
        assert body["industry"] is None
        assert body["price"] is None
        assert body["financials"] == []
        assert body["recent_tasks"]


async def test_company_detail_not_found():
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/companies/nope")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FIN-1004"


async def test_companies_require_auth():
    app = _app(api_token="tok")
    async with _client(app) as c:
        r = await c.get("/api/v1/companies")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "FIN-1002"
        d = await c.get("/api/v1/companies/300750.SZ")
        assert d.status_code == 401
        assert d.json()["error"]["code"] == "FIN-1002"


async def test_stats_aggregates_counts():
    """GET /api/v1/stats 返回真实计数（公司/任务/证据），计算数诚实为 0。"""
    async with _client(_app()) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await _submit_research(c, company="腾讯控股", ticker="0700", market="HK")
        await asyncio.sleep(0.05)
        resp = await c.get("/api/v1/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["companies_count"] == 2
        assert body["tasks_count"] == 2
        assert body["evidence_count"] == 0
        assert body["calculations_count"] == 0


async def test_stats_does_not_enrich_providers():
    """§3.1：/stats 只取计数，不触发 Provider 增强（registry 失败也不影响）。"""
    async with _client(_app(registry=FakeRegistry(fail=True))) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await asyncio.sleep(0.05)
        resp = await c.get("/api/v1/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["companies_count"] == 1
        assert body["tasks_count"] == 1


class CountingRegistry(FakeRegistry):
    """记录 invoke 调用次数，验证 MRU 缓存复用。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def invoke(self, factory, *, operation: str, market: str):
        self.calls += 1
        return await super().invoke(factory, operation=operation, market=market)


async def test_company_enrichment_mru_cache():
    """§3.1：同一公司重复读取时增强结果走 MRU 缓存，不重复调 Provider。"""
    reg = CountingRegistry()
    async with _client(_app(registry=reg)) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await asyncio.sleep(0.05)
        await c.get("/api/v1/companies/300750.SZ")
        first_calls = reg.calls
        assert first_calls >= 2  # profile + quote
        # 再次读取同一公司：命中缓存，不再调 Provider。
        await c.get("/api/v1/companies/300750.SZ")
        assert reg.calls == first_calls


async def test_company_list_deferred_enrichment():
    """§3.1 deferred enrichment：enrich=false 秒回基础数据，不触发 Provider 增强。"""
    reg = CountingRegistry()
    async with _client(_app(registry=reg)) as c:
        await _submit_research(c, company="宁德时代", ticker="300750.SZ", market="CN")
        await asyncio.sleep(0.05)
        # enrich=false：返回聚合基础数据，不调 Provider（行业/现价诚实为 null）。
        resp = await c.get("/api/v1/companies", params={"enrich": "false"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["ticker"] == "300750.SZ"
        assert item["name"] == "宁德时代"
        assert item["industry"] is None
        assert item["price"] is None
        assert reg.calls == 0, "enrich=false 不应触发 Provider 增强"
        # 默认 enrich=true：触发增强。
        await c.get("/api/v1/companies")
        assert reg.calls >= 2


async def test_stats_require_auth():
    app = _app(api_token="tok")
    async with _client(app) as c:
        r = await c.get("/api/v1/stats")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "FIN-1002"
