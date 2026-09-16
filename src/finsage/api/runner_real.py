"""真实工作流执行器（m08 ↔ m06 装配，§7/§16/§17）。

``RealWorkflowRunner`` 实现 ``WorkflowRunner`` 契约：调用已编译的 m06 Research QA 图
（:func:`build_research_qa`）真实推进工作流，并把最终 ``ResearchState`` 映射到
§26.9 SSE 事件与 ``handle.result``。

诚实性（AGENTS.md §10 / Honesty）：
- 检索命中数、财务指标数、计算数均取自图真实产出，绝不伪造；
- 未配置检索 / 财务依赖时（Milvus 未灌语料、Provider 未接入），对应字段为空列表，
  图据此诚实走 RAG / ABSTAIN，不伪装生产能力；
- 默认 ``build_deps`` 仍回退 ``DevRunner``；仅当显式开启 ``FIN_ENABLE_REAL_RUNNER``
  才注入本执行器（生产装配点）。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from finsage.api.app import AuditStoreProto, WorkflowRunner
from finsage.api.memory import InMemorySessionMemory, SessionMemory
from finsage.settings import Settings, get_settings
from finsage.workflows.nodes import WorkflowDeps


def _extract_query(input_: Any) -> str:
    """从 API 请求对象抽取查询文本（research.query / chat.message）。"""
    query = getattr(input_, "query", None)
    if query:
        return str(query)
    message = getattr(input_, "message", None)
    if message:
        return str(message)
    return str(input_)


def _request_session(input_: Any) -> str | None:
    """从请求对象取 session_id（无则为 None，表示新建会话/不启用记忆）。"""
    sid = getattr(input_, "session_id", None)
    return str(sid) if sid else None


def _answer_text(final: dict) -> str:
    """从图最终状态提取答案文本（无答案返回空串）。"""
    ans = final.get("final_answer")
    if ans is not None:
        return str(getattr(ans, "answer", ""))
    return ""


def _request_entities(input_: Any) -> list[Any]:
    """从请求的 company/ticker/market 构建预置实体（供图实体节点合并）。

    研究请求显式携带公司/代码，确定性注入，避免仅靠查询文本抽取（CN 数字代码、
    无"公司/集团/控股"后缀的中文名在纯文本中难以可靠识别）。
    """
    from finsage.models.entities import Entity

    entities: list[Any] = []
    ticker = getattr(input_, "ticker", None)
    market = getattr(input_, "market", None)
    company = getattr(input_, "company", None)
    if ticker:
        entities.append(
            Entity(
                type="ticker",
                value=str(ticker),
                normalized_value=str(ticker),
                market=market or "CN",
            )
        )
    if company:
        entities.append(
            Entity(
                type="company",
                value=str(company),
                normalized_value=str(company),
                market=market,
            )
        )
    return entities


def _evidence_to_view(ev: Any) -> dict[str, Any]:
    """把后端 Evidence 域对象映射为前端 EvidenceViewModel 扁平结构（§26.5）。

    后端 Evidence.source 是嵌套 SourceRef；前端期望扁平 camelCase 字段。
    """
    src = getattr(ev, "source", None)
    # 先绑定到具名变量，便于在 truthy 分支里把类型从 ``Any | None`` 收窄到 ``Any``
    # （避免跨两次 getattr 调用 mypy 无法关联，误报 ``None`` 无 isoformat 属性）。
    published_at = getattr(src, "published_at", None)
    retrieved_at = getattr(src, "retrieved_at", None)
    return {
        "id": getattr(ev, "id", ""),
        "documentId": getattr(ev, "document_id", ""),
        "chunkId": getattr(ev, "chunk_id", ""),
        "source": getattr(src, "source_id", None) or getattr(src, "provider", None) or "",
        "title": getattr(src, "title", "") or "",
        "page": getattr(src, "page", None),
        "section": getattr(src, "section", None),
        "excerpt": getattr(ev, "text", "") or "",
        "publishedAt": (
            published_at.isoformat() if published_at is not None else None
        ),
        "retrievedAt": (
            retrieved_at.isoformat() if retrieved_at is not None else ""
        ),
        "relevanceScore": float(getattr(ev, "relevance_score", 0) or 0),
        "authorityScore": float(getattr(ev, "authority_score", 0) or 0),
        "sourceUrl": getattr(src, "url", None),
    }


def _calculation_to_view(calc: Any) -> dict[str, Any]:
    """把后端 Calculation 域对象映射为前端 CalculationViewModel 扁平结构（§26.5）。"""
    inputs = getattr(calc, "inputs", {}) or {}
    return {
        "id": getattr(calc, "id", ""),
        "name": getattr(calc, "formula", "") or "",
        "formula": getattr(calc, "formula", "") or "",
        "inputs": [
            {"name": str(k), "value": str(v)} for k, v in inputs.items()
        ],
        "result": str(getattr(calc, "output_value", "") or ""),
        "unit": getattr(calc, "output_unit", None),
        "currency": getattr(calc, "output_currency", None),
        "period": getattr(calc, "period", None),
        "sourceEvidenceIds": list(getattr(calc, "source_evidence_ids", []) or []),
        "reproducible": True,
    }


class RealWorkflowRunner(WorkflowRunner):
    """真实工作流执行器：执行 m06 图并将真实产出映射到 §26.9 事件与结果。"""

    def __init__(
        self,
        deps: WorkflowDeps,
        audit: AuditStoreProto,
        *,
        graph_builder: Callable[..., Any] | None = None,
        checkpointer: Any = None,
        memory: SessionMemory | None = None,
    ) -> None:
        from finsage.agents.research_qa.graph import build_research_qa

        self._deps = deps
        self._audit = audit
        self._graph_builder = graph_builder or build_research_qa
        self._checkpointer = checkpointer
        # P0 会话记忆：注入 memory 后按 session_id 加载历史；缺省内存实现。
        self._memory = memory if memory is not None else InMemorySessionMemory()

    def _build_graph(self) -> Any:
        """装配图；配置了 checkpointer 时注入（ADR-0016 持久化）。"""
        if self._checkpointer is not None:
            return self._graph_builder(self._deps, checkpointer=self._checkpointer)
        return self._graph_builder(self._deps)

    async def run(self, kind: str, *, input_: Any, handle: Any) -> None:
        query = _extract_query(input_)
        graph = self._build_graph()
        init_state: dict[str, Any] = {
            "query": query,
            "trace_id": handle.trace_id,
            "task_id": handle.task_id,
            "tenant_id": getattr(handle, "tenant_id", None) or None,  # P0 检索跨租户隔离
            "entities": _request_entities(input_),
        }
        # P0 会话记忆接线：加载 session 历史注入状态，让 LLM 拿到续聊上下文。
        session_id = _request_session(input_)
        if session_id:
            init_state["chat_history"] = await asyncio.to_thread(
                self._memory.history, session_id
            )
        # ADR-0016 续跑接线（审计 §2.4）：checkpointer 靠 thread_id 定位快照，
        # 不传则持久化后端形同虚设（重启不可续跑）。thread_id 用 task_id —— 每个任务
        # 唯一，不会跨任务串状态。
        final = await graph.ainvoke(
            init_state,
            config={"configurable": {"thread_id": handle.task_id}},
        )

        # 会话记忆落库：记录本轮用户输入与助手回答。
        if session_id:
            await asyncio.to_thread(
                self._memory.append,
                session_id,
                "user",
                query,
                tenant_id=getattr(handle, "tenant_id", None) or "",
            )
            answer_text = _answer_text(final)
            if answer_text:
                await asyncio.to_thread(
                    self._memory.append,
                    session_id,
                    "assistant",
                    answer_text,
                    tenant_id=getattr(handle, "tenant_id", None) or "",
                )

        evidences = final.get("evidences") or []
        financial_data = final.get("financial_data") or []
        calculations = final.get("calculations") or []

        # 真实事件：命中 / 指标 / 计算数均来自图实际产出。
        handle.emit("workflow.stage", {"name": "parse", "status": "ok"})
        handle.emit("retrieval.completed", {"hits": len(evidences)})
        handle.emit("financial_data.completed", {"metrics": len(financial_data)})
        handle.emit("calculation.completed", {"count": len(calculations)})
        await asyncio.to_thread(
            self._audit.add,
            handle.trace_id,
            {"stage": "workflow", "type": kind, "status": "ok"},
            tenant_id=getattr(handle, "tenant_id", None) or "",
        )

        handle.set_progress(0.9)
        await asyncio.to_thread(
            self._audit.add,
            handle.trace_id,
            {"stage": "verification", "status": "ok"},
            tenant_id=getattr(handle, "tenant_id", None) or "",
        )

        final_answer = final.get("final_answer")
        if final_answer is None:
            result: dict[str, Any] = {
                "kind": kind,
                "abstained": True,
                "reason": final.get("error_code") or "no_final_answer",
            }
            answer_text = ""
            claims: list[Any] = []
            warnings: list[Any] = []
            confidence = 0.0
        else:
            answer_text = final_answer.answer
            claims = [c.model_dump() for c in final_answer.claims]
            warnings = list(final_answer.warnings or [])
            confidence = final_answer.confidence
            result = {
                "kind": kind,
                "answer": answer_text,
                "confidence": confidence,
                "claims": claims,
                "abstained": final_answer.confidence == 0.0,
                "error_code": final.get("error_code"),
                "warnings": warnings,
                # ADR-0018：辩论分歧度与情绪聚合此前在组装载荷时被丢弃，
                # 前端无法消费。为 None 时下发 null（前端不渲染，不伪造占位）。
                "disagreement": final_answer.disagreement,
                "sentiment_summary": (
                    final_answer.sentiment_summary.model_dump()
                    if final_answer.sentiment_summary is not None
                    else None
                ),
            }

        # 产出完整 happy-path 事件序列（§26.6 前端状态机要求
        # running→streaming→verifying→completed）：answer.delta 推进 streaming，
        # verification.started 推进 verifying，随后 _execute 发 task.completed 收尾。
        if answer_text:
            handle.emit("answer.delta", {"delta": answer_text})
        handle.emit(
            "answer.completed",
            {
                "answer": answer_text,
                "claims": claims,
                "evidences": [_evidence_to_view(e) for e in evidences],
                "calculations": [_calculation_to_view(c) for c in calculations],
                "citations": [],
                "confidence": confidence,
                "warnings": warnings,
                "audit_id": "",
                # ADR-0018：分歧度 / 情绪聚合同样进 SSE（前端据此渲染）。
                "disagreement": result.get("disagreement"),
                "sentiment_summary": result.get("sentiment_summary"),
            },
        )
        handle.emit("verification.started", {})
        handle.emit("verification.completed", {})
        handle.result = result


def build_default_workflow_deps(settings: Settings | None = None) -> WorkflowDeps:
    """装配默认真实依赖：LLM 按配置（真实 OpenAI 兼容或诚实 Dummy）。

    检索 / 财务依赖按开关装配（AGENTS.md §2 不猜接口，全部走既有域模块）：
    - ``enable_retrieval`` 为真 → 注入 Milvus 混合检索适配器；
    - ``enable_financial`` 为真 → 注入 build_registry() 财务适配器；
    - 未开启时对应字段为 ``None``，节点返回空列表，图据此诚实走 RAG / ABSTAIN。
    """
    settings = settings or get_settings()
    registry = _build_llm_registry(settings)
    llm = registry.get("default")
    llm_adversarial = registry.get_or_none("adversarial")
    retrieve = build_retriever(settings) if settings.enable_retrieval else None
    financial = build_financial(settings) if settings.enable_financial else None
    return WorkflowDeps(
        llm=llm,
        llm_adversarial=llm_adversarial,
        retrieve=retrieve,
        financial=financial,
        calc_runner=None,
    )


def build_retriever(
    settings: Settings | None = None,
) -> Callable[..., Awaitable[list[Any]]] | None:
    """构建 Milvus 混合检索适配器（接入 ``WorkflowDeps.retrieve``）。

    仅当 ``enable_retrieval`` 为真时返回 ``async (query, plan) -> [Evidence]``；
    否则返回 ``None``（节点诚实空检索）。适配器复用既有检索管线
    （BGE-M3 编码 → hybrid_search → build_evidence），不重复实现检索逻辑。
    """
    settings = settings or get_settings()
    if not settings.enable_retrieval:
        return None

    from finsage.ingestion.embedding import BGE3Embedder
    from finsage.retrieval.client import MilvusClientManager
    from finsage.retrieval.evidence import build_evidence
    from finsage.retrieval.search import hybrid_search

    async def _retrieve(query: str, plan: Any = None, *, tenant_id: str | None = None) -> list[Any]:
        # 嵌入/检索属外部基础设施；任一环节失败都属"检索失败"，
        # 诚实映射为 RetrievalError（节点据此置 error_code，不伪造命中）。
        try:
            embedder = BGE3Embedder(settings)
            dense, sparse = embedder.encode_text(query)
            manager = MilvusClientManager(settings)
            # P0 检索跨租户隔离：tenant_id 经 hybrid_search 的 Milvus expr 强制过滤，
            # 阻断跨租户检索泄露。
            result = hybrid_search(
                manager,
                query=query,
                dense_vector=dense,
                sparse_vector=sparse,
                tenant_id=tenant_id,
            )
        except Exception as exc:  # noqa: BLE001 - 基础设施失败统一归为检索错误
            from finsage.exceptions import RetrievalError

            raise RetrievalError(f"retrieval failed: {type(exc).__name__}") from exc
        return [
            build_evidence(hit=hit, source_meta={"provider": "milvus"})
            for hit in result.hits
        ]

    return _retrieve


def build_financial(
    settings: Settings | None = None,
    *,
    registry: Any | None = None,
) -> Callable[..., Awaitable[list[Any]]] | None:
    """构建财务 Provider 适配器（接入 ``WorkflowDeps.financial``）。

    仅当 ``enable_financial`` 为真时返回 ``async (q, entities) -> [FinancialMetric]``；
    否则返回 ``None``。适配器复用 ``build_registry()`` 的 failover 编排，绝不直接触及
    底层 SDK（AGENTS.md §4）；``registry`` 可注入用于测试。
    """
    settings = settings or get_settings()
    if not settings.enable_financial:
        return None

    from finsage.providers.finance.registry import ProviderRegistry

    reg: ProviderRegistry = registry or _build_registry()

    async def _financial(q: str, entities: list[Any]) -> list[Any]:
        out: list[Any] = []
        for e in entities or []:
            # 仅对 ticker 实体取财务（公司名实体无代码，跳过避免误调）。
            if getattr(e, "type", None) != "ticker":
                continue
            market = getattr(e, "market", None) or "CN"
            sym = getattr(e, "normalized_value", None) or getattr(e, "value", None)
            if not sym:
                continue
            # partial 在定义处绑定当前迭代的 sym/market（规避闭包延迟绑定），
            # 同时让 callable 定长为 Callable[[Any], Awaitable[Any]]，匹配 invoke 契约。
            # 注意：invoke 会把 provider 实例作为唯一位置参数喂给 factory，故 provider
            # 必须是 lambda 的末参（p）；首两参 s/m 绑定 sym/market，避免把 sym 错塞进
            # provider 槽位（曾触发 AttributeError: 'str' 无 get_financials 属性）。
            data = await reg.invoke(
                partial(lambda s, m, p: p.get_financials(s, m, "FY"), sym, market),
                operation="financials",
                market=market,
            )
            out.extend(data or [])
        return out

    return _financial


def _build_llm_registry(settings: Settings) -> Any:
    from finsage.providers.llm import build_llm_registry

    return build_llm_registry(settings)


def _build_registry() -> Any:
    from finsage.providers.finance import build_registry

    return build_registry()


def build_real_runner(
    audit: AuditStoreProto, *, settings: Settings | None = None
) -> RealWorkflowRunner:
    """构建真实执行器（生产装配点）。

    检索 / 财务依赖按 ``enable_retrieval`` / ``enable_financial`` 开关注入；
    默认仅装配 LLM，其余留空（诚实空检索 / 空财务）。
    会话记忆按 ``persistence_enabled`` 选择：持久化开启落 MySQL，否则内存。
    """
    settings = settings or get_settings()
    deps = build_default_workflow_deps(settings)
    from finsage.workflows.checkpoint import build_checkpointer

    checkpointer = build_checkpointer(settings)
    from finsage.api.memory import build_context_summarizer, build_session_memory

    # 上下文溢出摘要（ADR-0023）：复用已装配的 LLM（避免二次构造 provider）；
    # memory_summary_enabled 关闭时返回 None，历史压缩退回"丢弃最旧"。
    summarizer = build_context_summarizer(settings, llm_provider=getattr(deps, "llm", None))
    memory = build_session_memory(
        persistence_enabled=settings.persistence_enabled, summarizer=summarizer
    )
    return RealWorkflowRunner(deps, audit, checkpointer=checkpointer, memory=memory)


__all__ = [
    "RealWorkflowRunner",
    "build_real_runner",
    "build_default_workflow_deps",
    "build_retriever",
    "build_financial",
]
