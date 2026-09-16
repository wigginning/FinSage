"""m08 API + SSE integration tests（T809，§7/§8/§26.9）。

- 全端点（chat/research/tasks/documents/evidence/audit/stream）；
- §26.9 SSE 事件信封与终结事件；
- §8 错误契约：FIN 错误码 + 稳定 message，不泄露 Python exception 文本；
- 鉴权（Bearer token：缺省放行 / 缺失 FIN-1002 / 不匹配 FIN-1003）。

不依赖真实 DB / Milvus / 模型：注入替身 runner 与内存存储。
"""
from __future__ import annotations

import asyncio
import json

import httpx

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app
from finsage.api.identity_token import sign_token
from finsage.api.tasks import TaskHandle, TaskManager
from finsage.exceptions import WorkflowError
from finsage.settings import Settings


class FakeRunner:
    """成功替身：产出一组 §26.9 事件并完成。"""

    def __init__(self, audit: AuditStore) -> None:
        self.audit = audit

    async def run(self, kind: str, *, input_, handle: TaskHandle) -> None:
        handle.emit("workflow.stage", {"name": "parse", "status": "ok"})
        await asyncio.sleep(0)
        handle.emit("retrieval.completed", {"hits": 2})
        handle.emit("financial_data.completed", {"metrics": 3})
        handle.emit("calculation.completed", {"count": 1})
        handle.set_progress(0.8)
        self.audit.add(handle.trace_id, {"stage": "workflow", "kind": kind, "status": "ok"})
        self.audit.add(handle.trace_id, {"stage": "verification", "status": "ok"})
        # 完整 happy-path 事件序列（§26.6 前端状态机要求
        # running→streaming→verifying→completed）。
        handle.emit("answer.delta", {"delta": "ok"})
        handle.emit(
            "answer.completed",
            {
                "answer": "ok",
                "claims": [],
                "evidences": [],
                "calculations": [],
                "citations": [],
                "confidence": 0,
                "warnings": [],
                "audit_id": "",
            },
        )
        handle.emit("verification.started", {})
        handle.emit("verification.completed", {})
        handle.result = {"answer": "ok", "kind": kind}


class FailingRunner:
    """失败替身：抛 WorkflowError（验证 task.failed + error 事件不透传内部文本）。"""

    async def run(self, kind: str, *, input_, handle: TaskHandle) -> None:
        await asyncio.sleep(0)
        handle.emit("workflow.stage", {"name": "fetch", "status": "failed"})
        raise WorkflowError("boom-internal-secret")


class SlowRunner:
    """慢替身：长时间 await，供中止测试（任务保持 running 可被取消）。"""

    async def run(self, kind: str, *, input_, handle: TaskHandle) -> None:
        handle.emit("workflow.stage", {"name": "parse", "status": "ok"})
        await asyncio.sleep(30)


def _app(runner=None, *, api_token: str = "", tiny_files: bool = False):
    """装配测试应用。"""
    audit = AuditStore()
    deps = Deps(
        settings=Settings(api_token=api_token),
        task_manager=TaskManager(),
        runner=runner or FakeRunner(audit),
        files=FileStore(max_bytes=1024) if tiny_files else FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
    )
    return create_app(settings=Settings(api_token=api_token), deps=deps)


_ID_SECRET = "test-identity-secret"


def _app_with_identity(*, api_token: str = "svc-token"):
    """装配启用身份令牌的应用（api_token + identity_token_secret 同时配置）。"""
    audit = AuditStore()
    settings = Settings(api_token=api_token, identity_token_secret=_ID_SECRET)
    deps = Deps(
        settings=settings,
        task_manager=TaskManager(),
        runner=FakeRunner(audit),
        files=FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
    )
    return create_app(settings=settings, deps=deps)


def _bearer(user_id: str, tenant_id: str) -> dict[str, str]:
    token = sign_token(user_id=user_id, tenant_id=tenant_id, secret=_ID_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _submit_research(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/research", json={"query": "分析某公司2025年经营情况", "market": "CN"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["task_id"] and body["trace_id"]
    return body["task_id"]


async def test_chat_accepted():
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/chat", json={"message": "分析营收变化", "stream": True})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"task_id", "session_id", "trace_id", "status"}
        assert body["status"] == "accepted"


async def test_research_accepted_and_task_status():
    async with _client(_app()) as c:
        task_id = await _submit_research(c)
        await asyncio.sleep(0.05)  # 让后台任务推进状态机
        resp = await c.get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == task_id
        assert body["status"] in {"running", "completed"}
        assert 0 <= body["progress"] <= 1
        assert body["trace_id"]


async def test_task_not_found_error_contract():
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/tasks/does-not-exist")
        assert resp.status_code == 404
        err = resp.json()["error"]
        assert err["code"] == "FIN-1004"
        assert err["retryable"] is False
        assert err["trace_id"]
        assert "does-not-exist" not in err["message"]  # 不暴露内部细节


async def test_validation_error_contract():
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/chat", json={"message": ""})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "FIN-1001"


async def test_sse_stream_envelope_and_termination():
    async with _client(_app()) as c:
        task_id = await _submit_research(c)
        events = []
        async with c.stream("GET", f"/api/v1/tasks/{task_id}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))
        assert events
        # §26.9 信封字段齐全。
        first = events[0]
        assert {"event_id", "trace_id", "timestamp", "type", "data"} <= set(first)
        types = {e["type"] for e in events}
        assert "workflow.started" in types
        assert "task.completed" in types


async def test_sse_happy_path_emits_streaming_and_verifying_events():
    """§26.6 前端状态机要求 running→streaming→verifying→completed；
    SSE 流必须含 answer.delta / verification.started 等推进事件，否则前端卡在 running。"""
    async with _client(_app()) as c:
        task_id = await _submit_research(c)
        events = []
        async with c.stream("GET", f"/api/v1/tasks/{task_id}/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))
        types = [e["type"] for e in events]
        # 顺序：answer.delta 推进 streaming，verification.started 推进 verifying，
        # 最后 task.completed 收尾到 completed。
        assert types.index("answer.delta") < types.index("verification.started")
        assert types.index("verification.started") < types.index("task.completed")
        assert "answer.completed" in types
        assert "verification.completed" in types


async def test_sse_task_failed_masks_internal_message():
    app = _app(FailingRunner())
    async with _client(app) as c:
        task_id = await _submit_research(c)
        await asyncio.sleep(0.05)
        events = []
        async with c.stream("GET", f"/api/v1/tasks/{task_id}/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))
        types = {e["type"] for e in events}
        assert "task.failed" in types
        error_event = next(e for e in events if e["type"] == "error")
        assert error_event["data"]["code"] == "FIN-5001"
        raw = json.dumps(events, ensure_ascii=False)
        assert "boom-internal-secret" not in raw  # 内部异常文本不外泄


async def test_abort_running_task_emits_aborted():
    """§1.3：中止运行中的任务 → 状态 aborted，SSE 发 task.aborted。"""
    app = _app(SlowRunner())
    async with _client(app) as c:
        task_id = await _submit_research(c)
        await asyncio.sleep(0.05)  # 让任务进入 running
        resp = await c.post(f"/api/v1/tasks/{task_id}/abort")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == task_id
        assert body["status"] == "aborted"
        # 等待后台取消完成，SSE 应含 task.aborted。
        await asyncio.sleep(0.05)
        events = []
        async with c.stream("GET", f"/api/v1/tasks/{task_id}/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))
        types = {e["type"] for e in events}
        assert "task.aborted" in types
        assert "task.completed" not in types


async def test_abort_not_found_error_contract():
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/tasks/does-not-exist/abort")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FIN-1004"


async def test_abort_completed_is_idempotent():
    """§1.3：已终结任务再 abort 幂等返回当前状态，不重复发 task.aborted。"""
    async with _client(_app()) as c:
        task_id = await _submit_research(c)
        await asyncio.sleep(0.1)  # FakeRunner 快速完成
        resp = await c.post(f"/api/v1/tasks/{task_id}/abort")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


async def test_document_upload():
    async with _client(_app()) as c:
        resp = await c.post(
            "/api/v1/documents",
            files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"document_id", "status"}
        assert body["status"] == "accepted"


async def test_document_list_and_detail_include_traceability_fields():
    """§2.7：文档列表/详情返回 chunk_count / status / citation_count 溯源字段。"""
    async with _client(_app()) as c:
        up = await c.post(
            "/api/v1/documents",
            files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        doc_id = up.json()["document_id"]

        lst = await c.get("/api/v1/documents")
        assert lst.status_code == 200
        item = lst.json()["items"][0]
        assert item["document_id"] == doc_id
        assert item["chunk_count"] == 0
        assert item["status"] == "ingested"
        assert item["citation_count"] == 0

        det = await c.get(f"/api/v1/documents/{doc_id}")
        assert det.status_code == 200
        body = det.json()
        assert body["chunk_count"] == 0
        assert body["status"] == "ingested"
        assert body["citation_count"] == 0


async def test_document_too_large_error():
    async with _client(_app(tiny_files=True)) as c:
        big = b"x" * 4096
        resp = await c.post("/api/v1/documents", files={"file": ("big.bin", big)})
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "FIN-1102"


async def test_evidence_not_found_error():
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/evidence/unknown")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FIN-1004"


async def test_evidence_get_present():
    app = _app()
    app.state.deps.evidence.add(
        "ev-1", {"id": "ev-1", "content": "x", "source": "s1", "confidence": 0.9}
    )
    async with _client(app) as c:
        resp = await c.get("/api/v1/evidence/ev-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "ev-1"


async def test_audit_by_trace():
    app = _app()
    app.state.deps.audit.add("trace-abc", {"stage": "workflow", "status": "ok"})
    async with _client(app) as c:
        resp = await c.get("/api/v1/audit/trace-abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trace_id"] == "trace-abc"
        assert len(body["events"]) == 1
        assert body["events"][0]["stage"] == "workflow"


async def test_auth_required_and_forbidden():
    app = _app(api_token="secret-token")
    async with _client(app) as c:
        no_token = await c.post("/api/v1/chat", json={"message": "hi"})
        assert no_token.status_code == 401
        assert no_token.json()["error"]["code"] == "FIN-1002"

        bad = await c.post(
            "/api/v1/chat", json={"message": "hi"}, headers={"Authorization": "Bearer wrong"}
        )
        assert bad.status_code == 403
        assert bad.json()["error"]["code"] == "FIN-1003"

        ok = await c.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "accepted"


async def test_openapi_schema_generated():
    """OpenAPI 可生成（§30.4 API DoD）。"""
    async with _client(_app()) as c:
        resp = await c.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "/api/v1/chat" in schema["paths"]
        assert "/api/v1/research" in schema["paths"]
        assert "/api/v1/tasks/{task_id}/stream" in schema["paths"]
        assert schema["info"]["title"]


# ---------------------------------------------------------------------------
# P0 权限：身份令牌 / IDOR 归属校验 / 租户隔离
# ---------------------------------------------------------------------------


async def test_research_task_records_request_tenant():
    """创建任务时应记录请求身份的 tenant_id（供后续 IDOR 校验）。"""
    app = _app_with_identity()
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/research",
            json={"query": "分析某公司", "market": "CN"},
            headers=_bearer("u1", "tenant-a"),
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        handle = app.state.deps.task_manager.get(task_id)
        assert handle.tenant_id == "tenant-a"


async def test_idor_task_read_cross_tenant_forbidden():
    """P0 IDOR：A 租户创建的任务，B 租户读取应 403。"""
    app = _app_with_identity()
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/research",
            json={"query": "分析某公司", "market": "CN"},
            headers=_bearer("u1", "tenant-a"),
        )
        task_id = resp.json()["task_id"]

        # 本租户可读。
        ok = await c.get(f"/api/v1/tasks/{task_id}", headers=_bearer("u2", "tenant-a"))
        assert ok.status_code == 200

        # 跨租户读被拒。
        denied = await c.get(f"/api/v1/tasks/{task_id}", headers=_bearer("u2", "tenant-b"))
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FIN-1003"


async def test_idor_task_stream_cross_tenant_forbidden():
    app = _app_with_identity()
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/research",
            json={"query": "分析某公司", "market": "CN"},
            headers=_bearer("u1", "tenant-a"),
        )
        task_id = resp.json()["task_id"]
        denied = await c.get(f"/api/v1/tasks/{task_id}/stream", headers=_bearer("u2", "tenant-b"))
        assert denied.status_code == 403


async def test_idor_task_abort_cross_tenant_forbidden():
    app = _app_with_identity()
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/research",
            json={"query": "分析某公司", "market": "CN"},
            headers=_bearer("u1", "tenant-a"),
        )
        task_id = resp.json()["task_id"]
        denied = await c.post(f"/api/v1/tasks/{task_id}/abort", headers=_bearer("u2", "tenant-b"))
        assert denied.status_code == 403


async def test_idor_task_list_filtered_by_tenant():
    """P0 租户隔离：列表接口只返回本租户任务。"""
    app = _app_with_identity()
    async with _client(app) as c:
        await c.post(
            "/api/v1/research",
            json={"query": "分析A公司", "market": "CN"},
            headers=_bearer("u1", "tenant-a"),
        )
        await c.post(
            "/api/v1/research",
            json={"query": "分析B公司", "market": "CN"},
            headers=_bearer("u1", "tenant-b"),
        )
        await asyncio.sleep(0.05)
        lst = await c.get("/api/v1/tasks", headers=_bearer("u1", "tenant-a"))
        assert lst.status_code == 200
        items = lst.json()["items"]
        assert len(items) == 1  # 只看到本租户任务
        assert items[0]["query"] == "分析A公司"


async def test_anonymous_static_token_still_works():
    """未配置 identity secret 时，静态 api_token 请求仍可正常完成（兼容）。"""
    app = _app(api_token="secret-token")
    async with _client(app) as c:
        resp = await c.post(
            "/api/v1/research",
            json={"query": "分析某公司", "market": "CN"},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"


async def test_idor_document_cross_tenant_forbidden():
    """P0 IDOR：文档读接口按租户隔离。"""
    app = _app_with_identity()
    async with _client(app) as c:
        up = await c.post(
            "/api/v1/documents",
            files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers=_bearer("u1", "tenant-a"),
        )
        doc_id = up.json()["document_id"]
        assert up.status_code == 200

        # 本租户可读。
        ok = await c.get(f"/api/v1/documents/{doc_id}", headers=_bearer("u2", "tenant-a"))
        assert ok.status_code == 200

        # 跨租户读被拒。
        denied = await c.get(f"/api/v1/documents/{doc_id}", headers=_bearer("u2", "tenant-b"))
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FIN-1003"


async def test_idor_document_list_filtered_by_tenant():
    app = _app_with_identity()
    async with _client(app) as c:
        await c.post(
            "/api/v1/documents",
            files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers=_bearer("u1", "tenant-a"),
        )
        await c.post(
            "/api/v1/documents",
            files={"file": ("b.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers=_bearer("u1", "tenant-b"),
        )
        lst = await c.get("/api/v1/documents", headers=_bearer("u1", "tenant-a"))
        assert lst.status_code == 200
        items = lst.json()["items"]
        assert len(items) == 1  # 只看到本租户文档
        assert items[0]["filename"] == "a.pdf"


async def test_idor_evidence_cross_tenant_forbidden():
    app = _app_with_identity()
    app.state.deps.evidence.add(
        "ev-1", {"id": "ev-1", "content": "x"}, tenant_id="tenant-a"
    )
    async with _client(app) as c:
        ok = await c.get("/api/v1/evidence/ev-1", headers=_bearer("u2", "tenant-a"))
        assert ok.status_code == 200
        denied = await c.get("/api/v1/evidence/ev-1", headers=_bearer("u2", "tenant-b"))
        assert denied.status_code == 403


async def test_idor_audit_cross_tenant_forbidden():
    app = _app_with_identity()
    app.state.deps.audit.add("trace-a", {"stage": "workflow"}, tenant_id="tenant-a")
    async with _client(app) as c:
        ok = await c.get("/api/v1/audit/trace-a", headers=_bearer("u2", "tenant-a"))
        assert ok.status_code == 200
        denied = await c.get("/api/v1/audit/trace-a", headers=_bearer("u2", "tenant-b"))
        assert denied.status_code == 403