"""FinEval 评估 API 集成测试（ADR-0022）。

覆盖：
- POST /api/v1/evaluations 异步入队 → GET /{task_id} 拿到真实指标（不落库路径）；
- 数据集裁剪（task_types / limit_per_type）与非法取值 FIN-1001；
- 未知 task_id / 非评估任务 → FIN-1004；
- 列表端点分页；
- router 级 require_auth（缺 token → FIN-1002）；
- 缺执行器 → 任务 failed（诚实失败，不返回编造的 0 分报告）。

不依赖真实 DB / Milvus / 模型：``persistence_enabled`` 关闭走内存缓冲 store，
executor 用 DevEvalExecutor（返回 None，evaluator 据实评分）。
"""
from __future__ import annotations

import asyncio

import httpx

from finsage.api import AuditStore, Deps, EvidenceStore, FileStore, create_app
from finsage.api.tasks import TaskManager
from finsage.evaluation.executors import build_dev_executor
from finsage.settings import Settings


class FakeRunner:
    """chat/research 用替身（评估路径不经它，但 Deps 要求非空）。"""

    async def run(self, kind: str, *, input_, handle) -> None:
        handle.result = {"kind": kind}


def _app(*, api_token: str = "", executor=None, with_executor: bool = True):
    audit = AuditStore()
    settings = Settings(api_token=api_token, rate_limit_enabled=False)
    deps = Deps(
        settings=settings,
        task_manager=TaskManager(),
        runner=FakeRunner(),
        files=FileStore(),
        evidence=EvidenceStore(),
        audit=audit,
        evaluation_executor=(executor or build_dev_executor()) if with_executor else None,
    )
    return create_app(settings=settings, deps=deps)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _wait_done(client: httpx.AsyncClient, task_id: str, *, tries: int = 60) -> dict:
    """轮询到任务终结（评估用例数少，通常 1–2 轮即完成）。"""
    for _ in range(tries):
        resp = await client.get(f"/api/v1/evaluations/{task_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in {"completed", "failed", "aborted"}:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"evaluation {task_id} did not finish: {body}")


async def test_submit_and_fetch_metrics():
    """入队 → 完成后返回由实际 outcomes 聚合的指标。"""
    async with _client(_app()) as c:
        resp = await c.post(
            "/api/v1/evaluations", json={"task_types": ["numeric"], "limit_per_type": 3}
        )
        assert resp.status_code == 200, resp.text
        submitted = resp.json()
        assert submitted["status"] == "accepted"
        assert submitted["case_count"] == 3
        assert submitted["dataset_version"]

        body = await _wait_done(c, submitted["task_id"])
        assert body["status"] == "completed", body
        assert body["progress"] == 1.0
        assert body["case_count"] == 3
        assert body["evaluated_count"] == 3
        # 缺省执行器诚实标记：调用方据此知道这不是真实端到端评测。
        assert body["executor"] == "DevEvalExecutor"
        assert body["persisted"] is False
        # run_id 只在落库时生成（本例内存缓冲 store 仍会分配，用于重放定位）。
        metrics = body["metrics"]
        assert metrics["overall"]["total"] == 3
        assert set(metrics["per_type"]) == {"numeric"}
        assert metrics["per_type"]["numeric"]["total"] == 3
        # 指标由实际评分产生：pass_rate 与 passed/total 自洽（非硬编码）。
        overall = metrics["overall"]
        assert overall["pass_rate"] == round(overall["passed"] / overall["total"], 4)


async def test_full_benchmark_case_count():
    """不传裁剪参数即提交完整基准（100 条）。"""
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/evaluations", json={})
        assert resp.status_code == 200
        assert resp.json()["case_count"] == 100


async def test_unknown_task_type_rejected_at_submit():
    """非法 task_type 在提交时即 FIN-1001，不制造必然失败的后台任务。"""
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/evaluations", json={"task_types": ["not-a-type"]})
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "FIN-1001"
        # 未产生任务
        listed = await c.get("/api/v1/evaluations")
        assert listed.json()["total"] == 0


async def test_limit_per_type_out_of_range_is_rejected():
    """limit_per_type 超出 1..20 由 pydantic 拦下，经 §8 处理器折成 400/FIN-1001。"""
    async with _client(_app()) as c:
        resp = await c.post("/api/v1/evaluations", json={"limit_per_type": 99})
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "FIN-1001"


async def test_unknown_run_returns_not_found():
    async with _client(_app()) as c:
        resp = await c.get("/api/v1/evaluations/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FIN-1004"


async def test_non_evaluation_task_is_not_visible():
    """chat 任务不得经评估端点读取（kind 隔离）。"""
    app = _app()
    async with _client(app) as c:
        chat = await c.post("/api/v1/chat", json={"message": "hi"})
        assert chat.status_code == 200, chat.text
        task_id = chat.json()["task_id"]
        resp = await c.get(f"/api/v1/evaluations/{task_id}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "FIN-1004"


async def test_list_pagination():
    async with _client(_app()) as c:
        for _ in range(3):
            r = await c.post(
                "/api/v1/evaluations", json={"task_types": ["numeric"], "limit_per_type": 1}
            )
            assert r.status_code == 200
        resp = await c.get("/api/v1/evaluations", params={"limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["limit"] == 2 and body["offset"] == 0


async def test_requires_auth_when_token_configured():
    """router 级 require_auth：配置了 api_token 时缺 token → FIN-1002。"""
    async with _client(_app(api_token="secret")) as c:
        resp = await c.post("/api/v1/evaluations", json={})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "FIN-1002"
        resp = await c.get("/api/v1/evaluations", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200


async def test_missing_executor_fails_honestly():
    """未装配执行器 → 任务 failed + FIN-6001，绝不返回编造的空报告。"""
    async with _client(_app(with_executor=False)) as c:
        resp = await c.post(
            "/api/v1/evaluations", json={"task_types": ["numeric"], "limit_per_type": 1}
        )
        assert resp.status_code == 200
        body = await _wait_done(c, resp.json()["task_id"])
        assert body["status"] == "failed", body
        assert body["error_code"] == "FIN-6001"
        assert body["metrics"] is None
