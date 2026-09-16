"""RealWorkflowRunner（真实 m06 图执行器）装配与诚实性测试。

覆盖：
- 真实执行 m06 图并映射 §26.9 事件 / handle.result（不再是 DevRunner 桩字符串）；
- 检索命中数等事件取自图真实产出（绝不伪造）；
- build_deps 默认仍走 DevRunner，仅 enable_real_runner=True 时注入真实执行器。
"""
from __future__ import annotations

from types import SimpleNamespace

from finsage.api.app import AuditStore, DevRunner, build_deps
from finsage.api.runner_real import (
    RealWorkflowRunner,
    _calculation_to_view,
    _evidence_to_view,
    build_real_runner,
)
from finsage.api.schemas import ChatRequest, ResearchRequest
from finsage.financial.models import Calculation
from finsage.models.sources import Evidence, SourceRef
from finsage.providers.llm import DummyLLMProvider
from finsage.settings import Settings
from finsage.workflows.nodes import WorkflowDeps

_DEV_STUB = "dev-runner stub（真实执行由 m06+m07 装配）"


async def test_real_runner_executes_real_graph_not_stub():
    audit = AuditStore()
    deps = WorkflowDeps(llm=DummyLLMProvider(), retrieve=None, financial=None)
    runner = RealWorkflowRunner(deps, audit)

    from finsage.api.tasks import TaskHandle

    handle = TaskHandle(task_id="t1", trace_id="tr1")
    req = ResearchRequest(query="茅台 2023 年营收多少？")
    await runner.run("research", input_=req, handle=handle)

    # 不再返回 DevRunner 桩字符串。
    assert isinstance(handle.result, dict)
    assert handle.result.get("answer") != _DEV_STUB
    assert handle.result["kind"] == "research"

    event_types = [e.type for e in handle._buffer]
    assert "retrieval.completed" in event_types
    # 未配置检索依赖 -> 命中数诚实为 0，而非伪造常量。
    retrieval = next(e for e in handle._buffer if e.type == "retrieval.completed")
    assert retrieval.data["hits"] == 0


async def test_real_runner_passes_thread_id_for_persistent_checkpoint():
    """ADR-0016 续跑接线（审计 §2.4）：checkpointer 靠 thread_id 定位快照。

    不传 thread_id 时，即便后端配成 mysql/redis，LangGraph 也找不到快照，
    重启仍不可续跑 —— 持久化后端形同虚设。
    """
    from finsage.api.tasks import TaskHandle

    captured: dict[str, object] = {}

    class _FakeGraph:
        async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
            captured["config"] = config or {}
            return {"final_answer": None, "evidences": [], "calculations": []}

    audit = AuditStore()
    deps = WorkflowDeps(llm=DummyLLMProvider(), retrieve=None, financial=None)
    runner = RealWorkflowRunner(deps, audit, graph_builder=lambda *_a, **_k: _FakeGraph())

    handle = TaskHandle(task_id="task-abc", trace_id="tr9")
    await runner.run("research", input_=ResearchRequest(query="测试"), handle=handle)

    config = captured["config"]
    assert isinstance(config, dict)
    # thread_id 用 task_id：每个任务唯一，不跨任务串状态。
    assert config["configurable"]["thread_id"] == "task-abc"


async def test_real_runner_emits_happy_path_streaming_verifying_events():
    """§26.6 前端状态机要求 running→streaming→verifying→completed；
    真实执行器必须产出 answer.delta / verification.started 等推进事件。"""
    audit = AuditStore()
    deps = WorkflowDeps(llm=DummyLLMProvider(), retrieve=None, financial=None)
    runner = RealWorkflowRunner(deps, audit)

    from finsage.api.tasks import TaskHandle

    handle = TaskHandle(task_id="t4", trace_id="tr4")
    await runner.run(
        "research", input_=ResearchRequest(query="茅台 2023 年营收多少？"), handle=handle
    )

    types = [e.type for e in handle._buffer]
    assert "answer.delta" in types
    assert "answer.completed" in types
    assert "verification.started" in types
    assert "verification.completed" in types
    # 顺序：answer.delta 推进 streaming，verification.started 推进 verifying。
    assert types.index("answer.delta") < types.index("verification.started")


async def test_real_runner_honest_retrieval_hit_count():
    ev_a = SimpleNamespace(id="e1", text="证据一", relevance_score=0.9)
    ev_b = SimpleNamespace(id="e2", text="证据二", relevance_score=0.7)

    async def fake_retrieve(query, plan, *, tenant_id=None):  # noqa: ANN001
        return [ev_a, ev_b]

    audit = AuditStore()
    deps = WorkflowDeps(llm=DummyLLMProvider(), retrieve=fake_retrieve, financial=None)
    runner = RealWorkflowRunner(deps, audit)

    from finsage.api.tasks import TaskHandle

    handle = TaskHandle(task_id="t2", trace_id="tr2")
    await runner.run("research", input_=ResearchRequest(query="某公司财务情况"), handle=handle)

    retrieval = next(e for e in handle._buffer if e.type == "retrieval.completed")
    assert retrieval.data["hits"] == 2  # 真实计数，非伪造


async def test_real_runner_extracts_chat_message():
    audit = AuditStore()
    deps = WorkflowDeps(llm=DummyLLMProvider(), retrieve=None, financial=None)
    runner = RealWorkflowRunner(deps, audit)

    from finsage.api.tasks import TaskHandle

    handle = TaskHandle(task_id="t3", trace_id="tr3")
    await runner.run("chat", input_=ChatRequest(message="请解释净利率"), handle=handle)

    assert handle.result["kind"] == "chat"
    assert handle.result.get("answer") != _DEV_STUB


async def test_build_deps_default_uses_dev_runner():
    # 显式关闭 real runner，避免受 .env（FIN_ENABLE_REAL_RUNNER）影响。
    deps = build_deps(settings=Settings(enable_real_runner=False))
    assert isinstance(deps.runner, DevRunner)
    assert not isinstance(deps.runner, RealWorkflowRunner)


async def test_build_deps_real_runner_when_enabled():
    from finsage.settings import Settings

    deps = build_deps(settings=Settings(enable_real_runner=True))
    assert isinstance(deps.runner, RealWorkflowRunner)


async def test_build_real_runner_returns_real_runner():
    runner = build_real_runner(AuditStore())
    assert isinstance(runner, RealWorkflowRunner)


def test_evidence_to_view_flattens_to_frontend_shape():
    """§2.6：后端 Evidence 域对象映射为前端 EvidenceViewModel 扁平 camelCase。"""
    from datetime import UTC, datetime

    ev = Evidence(
        id="ev1",
        document_id="doc1",
        chunk_id="chunk1",
        source=SourceRef(
            source_id="src1",
            provider="milvus",
            title="宁德时代2024年报",
            page=3,
            section="财务",
            url="https://example.com",
            published_at=datetime(2024, 12, 31, tzinfo=UTC),
            retrieved_at=datetime(2026, 8, 26, tzinfo=UTC),
            authority_tier=3,
        ),
        text="营收 3620.6 亿元",
        relevance_score=0.9,
        authority_score=0.7,
    )
    view = _evidence_to_view(ev)
    assert view["id"] == "ev1"
    assert view["documentId"] == "doc1"
    assert view["chunkId"] == "chunk1"
    assert view["source"] == "src1"
    assert view["title"] == "宁德时代2024年报"
    assert view["page"] == 3
    assert view["excerpt"] == "营收 3620.6 亿元"
    assert view["relevanceScore"] == 0.9
    assert view["authorityScore"] == 0.7
    assert view["sourceUrl"] == "https://example.com"


def test_calculation_to_view_flattens_to_frontend_shape():
    """§2.6：后端 Calculation 域对象映射为前端 CalculationViewModel。"""
    from decimal import Decimal

    calc = Calculation(
        formula="net_income / revenue",
        inputs={"net_income": Decimal("722.01"), "revenue": Decimal("4237.02")},
        output_value=Decimal("0.1704"),
        output_unit="ratio",
        period="2025-12-31",
        source_evidence_ids=["ev1"],
    )
    view = _calculation_to_view(calc)
    assert view["formula"] == "net_income / revenue"
    assert view["result"] == "0.1704"
    assert view["unit"] == "ratio"
    assert view["period"] == "2025-12-31"
    assert view["sourceEvidenceIds"] == ["ev1"]
    assert view["reproducible"] is True
    assert {"name": "revenue", "value": "4237.02"} in view["inputs"]
