"""m08 列表/读接口集成测试：tasks / documents 列表与文档详情。

- GET /api/v1/tasks：分页 + status/kind 筛选 + created_at 倒序；
- GET /api/v1/documents：分页列表；
- GET /api/v1/documents/{id}：存在返回 200、不存在返回 FIN-1004；
- 新端点继承 router 级 require_auth（缺 token → FIN-1002）。

不依赖真实 DB / Milvus / 模型：注入替身 runner 与内存存储。
"""
from __future__ import annotations

import asyncio

import httpx

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app
from finsage.api.tasks import TaskManager
from finsage.settings import Settings


class FakeRunner:
    """成功替身：产出一组事件并完成。"""

    def __init__(self, audit: AuditStore) -> None:
        self.audit = audit

    async def run(self, kind: str, *, input_, handle) -> None:
        handle.emit("workflow.stage", {"name": "parse", "status": "ok"})
        self.audit.add(handle.trace_id, {"stage": "workflow", "kind": kind, "status": "ok"})
        handle.result = {"answer": "ok", "kind": kind}


def _app(api_token: str = ""):
    audit = AuditStore()
    deps = Deps(
        settings=Settings(api_token=api_token),
        task_manager=TaskManager(),
        runner=FakeRunner(audit),
        files=FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
    )
    return create_app(settings=Settings(api_token=api_token), deps=deps)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _submit_research(client: httpx.AsyncClient) -> str:
    resp = await client.post("/api/v1/research", json={"query": "q", "market": "CN"})
    assert resp.status_code == 200
    return resp.json()["task_id"]


async def test_tasks_list_empty():
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


async def test_tasks_list_pagination_and_filter():
    async with _client(_app()) as c:
        await _submit_research(c)
        await _submit_research(c)
        await asyncio.sleep(0.05)
        resp = await c.get("/api/v1/tasks", params={"limit": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 1
        first = body["items"][0]
        assert set(first) == {
            "task_id",
            "kind",
            "status",
            "progress",
            "trace_id",
            "created_at",
            "error_code",
            "query",
            "company",
            "ticker",
            "duration_sec",
        }
        assert first["kind"] == "research"

        resp2 = await c.get("/api/v1/tasks", params={"status": "completed"})
        assert resp2.status_code == 200
        assert resp2.json()["total"] >= 1


async def test_documents_list_and_detail():
    async with _client(_app()) as c:
        up = await c.post(
            "/api/v1/documents", files={"file": ("r.pdf", b"%PDF fake", "application/pdf")}
        )
        assert up.status_code == 200
        doc_id = up.json()["document_id"]

        lst = await c.get("/api/v1/documents")
        assert lst.status_code == 200
        lbody = lst.json()
        assert lbody["total"] == 1
        item = lbody["items"][0]
        assert item["document_id"] == doc_id
        assert item["filename"] == "r.pdf"
        assert item["size"] == len(b"%PDF fake")
        assert item["created_at"]

        det = await c.get(f"/api/v1/documents/{doc_id}")
        assert det.status_code == 200
        assert det.json()["document_id"] == doc_id


async def test_document_detail_not_found():
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/documents/nope")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FIN-1004"


async def test_list_endpoints_require_auth():
    app = _app(api_token="tok")
    async with _client(app) as c:
        r = await c.get("/api/v1/tasks")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "FIN-1002"
        d = await c.get("/api/v1/documents")
        assert d.status_code == 401
        assert d.json()["error"]["code"] == "FIN-1002"


async def test_tasks_list_carries_query_company():
    """research 提交的主题/公司须透传至列表视图（§7.3 TaskSummary 扩展）。"""
    async with _client(_app()) as c:
        resp = await c.post(
            "/api/v1/research",
            json={
                "query": "宁德时代毛利率分析",
                "company": "宁德时代",
                "ticker": "300750.SZ",
                "market": "CN",
            },
        )
        assert resp.status_code == 200
        await asyncio.sleep(0.05)
        lst = await c.get("/api/v1/tasks", params={"kind": "research"})
        assert lst.status_code == 200
        items = lst.json()["items"]
        assert items, "应至少返回一条 research 任务"
        top = items[0]
        assert top["query"] == "宁德时代毛利率分析"
        assert top["company"] == "宁德时代"
        assert top["ticker"] == "300750.SZ"


async def test_tasks_list_chat_has_null_query():
    """chat 类任务不携带主题/公司，列表对应字段为 null。"""
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/chat", json={"message": "hi"})
        assert resp.status_code == 200
        await asyncio.sleep(0.05)
        lst = await c.get("/api/v1/tasks", params={"kind": "chat"})
        assert lst.status_code == 200
        items = lst.json()["items"]
        assert items
        assert items[0]["query"] is None
        assert items[0]["company"] is None


async def test_tasks_list_keyword_filter():
    """§2.1：/tasks 支持 keyword 过滤（匹配 query/company/ticker）。"""
    async with _client(_app()) as c:
        await c.post(
            "/api/v1/research",
            json={
                "query": "宁德时代毛利率分析",
                "company": "宁德时代",
                "ticker": "300750.SZ",
                "market": "CN",
            },
        )
        await c.post(
            "/api/v1/research",
            json={"query": "腾讯控股估值", "company": "腾讯控股", "ticker": "0700", "market": "HK"},
        )
        await asyncio.sleep(0.05)
        hit = await c.get("/api/v1/tasks", params={"keyword": "宁德"})
        assert hit.status_code == 200
        assert hit.json()["total"] == 1
        assert hit.json()["items"][0]["company"] == "宁德时代"
        miss = await c.get("/api/v1/tasks", params={"keyword": "不存在"})
        assert miss.json()["total"] == 0


async def test_documents_list_keyword_filter():
    """§2.1：/documents 支持 keyword 过滤（匹配 filename）。"""
    async with _client(_app()) as c:
        await c.post(
            "/api/v1/documents",
            files={"file": ("宁德时代年报.pdf", b"%PDF", "application/pdf")},
        )
        await c.post(
            "/api/v1/documents",
            files={"file": ("腾讯财报.pdf", b"%PDF", "application/pdf")},
        )
        hit = await c.get("/api/v1/documents", params={"keyword": "宁德"})
        assert hit.status_code == 200
        assert hit.json()["total"] == 1
        assert hit.json()["items"][0]["filename"] == "宁德时代年报.pdf"
        miss = await c.get("/api/v1/documents", params={"keyword": "不存在"})
        assert miss.json()["total"] == 0
