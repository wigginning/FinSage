"""Research QA LangGraph 装配（§17 —— m06 T603）。

节点复用 :mod:`finsage.workflows.nodes` 的共享工厂，经 WorkflowDeps 注入依赖。
图中条件路由（§16.6）由 :func:`choose_route` 决定，最终是否作答由
:func:`_after_verification` 决定（校验 FAIL / 数据缺失 -> 弃权）。

拓扑（§17）：
    START -> parse_query -> intent -> entity -> policy -> route
    route -RAG/COMBINED-> retrieval -> financial_data -> calculation
         -FINANCIAL_MCP-> financial_data
         -ABSTAIN-> abstain
    financial_data -> calculation -> evidence -> claim -> sentiment -> debate
                  -> verification
    verification -PASS-> answer  /  -FAIL|ABSTAIN|error-> abstain
    answer|abstain -> audit -> END

约束：
- 仅 answer_node / abstention_node 写 final_answer（§15）；
- 硬错误写入 error_code，由路由决策支配，不外抛。
"""
from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from langgraph.graph import END, START, StateGraph

from finsage.workflows.nodes import (
    WorkflowDeps,
    choose_route,
    make_abstention,
    make_answer,
    make_audit,
    make_calculation,
    make_claim_generation,
    make_debate,
    make_entity,
    make_evidence_selection,
    make_financial_data,
    make_intent,
    make_parse_query,
    make_policy,
    make_retrieval,
    make_route,
    make_sentiment,
    make_verification,
)
from finsage.workflows.reliability import RetryPolicy, state_aware_retry, with_timeout
from finsage.workflows.state import ResearchState

# route 条件边的目标映射（§16.6）。COMBINED 先走 retrieval 聚合检索与财务。
# add_conditional_edges 的 path_map 期望 dict[Hashable, str]（dict 的键类型不变），
# 故显式标注为 dict[Hashable, str]（键为 str，天然 Hashable）。
_ROUTE_MAP: dict[Hashable, str] = {
    "RAG": "retrieval",
    "FINANCIAL_MCP": "financial_data",
    "COMBINED": "retrieval",
    "ABSTAIN": "abstain",
}

# verification 后的条件路由：_after_verification 直接返回目标节点名。
_VERIFY_MAP: dict[Hashable, str] = {"answer": "answer", "abstain": "abstain"}


def _after_verification(state: dict) -> str:
    """校验后路由：任何未处理错误或未 PASS 一律弃权，确保 error 不给答案。"""
    if state.get("error_code"):
        return "abstain"
    vr = state.get("verification_result")
    status = getattr(vr, "status", "ABSTAIN")
    return "answer" if status == "PASS" else "abstain"


def build_research_qa(
    deps: WorkflowDeps | None = None,
    *,
    checkpointer: Any = None,
    timeouts: dict[str, float] | None = None,
    retry_policy: RetryPolicy | None = None,
    node_timeout: float = 0,
):
    """装配并编译 Research QA 图（§17）。

    deps          节点外部依赖（默认空依赖：外部 IO 均 no-op，便于测试）。
    checkpointer  LangGraph BaseCheckpointSaver（T607）；None 时不持久化。
    timeouts      node 名 -> 超时秒数（T608），仅对 async IO 节点生效；
                  命中超时写 ``error_code=FIN-5002`` 并由路由弃权。
    retry_policy  对 retrieval / financial_data 启用有界确定性重试（T608）。
    node_timeout  便捷传参：对所有 IO 节点统一超时秒数（0 禁用）。
    """
    deps = deps or WorkflowDeps()
    timeouts = dict(timeouts or {})

    def _io_node(bare: Any, name: str) -> Any:
        """对 IO 节点叠加 retry/timeout（timeout 限界整个重试循环）。"""
        if retry_policy:
            bare = state_aware_retry(bare, retry_policy)
        secs = timeouts.get(name, node_timeout)
        if secs and secs > 0:
            bare = with_timeout(bare, secs)
        return bare

    graph = StateGraph(ResearchState)

    graph.add_node("parse_query", make_parse_query(deps))
    graph.add_node("intent", make_intent(deps))
    graph.add_node("entity", make_entity(deps))
    graph.add_node("policy", make_policy(deps))
    graph.add_node("route", make_route(deps))
    graph.add_node("retrieval", _io_node(make_retrieval(deps), "retrieval"))
    graph.add_node("financial_data", _io_node(make_financial_data(deps), "financial_data"))
    graph.add_node("calculation", make_calculation(deps))
    graph.add_node("evidence", make_evidence_selection(deps))
    graph.add_node("claim", make_claim_generation(deps))
    # ADR-0018：情绪富化（规则法，确定性，不调用 LLM）。
    graph.add_node("sentiment", make_sentiment(deps))
    graph.add_node("debate", make_debate(deps))
    graph.add_node("verification", make_verification(deps))
    graph.add_node("answer", make_answer(deps))
    graph.add_node("abstain", make_abstention(deps))
    graph.add_node("audit", make_audit(deps))

    graph.add_edge(START, "parse_query")
    graph.add_edge("parse_query", "intent")
    graph.add_edge("intent", "entity")
    graph.add_edge("entity", "policy")
    graph.add_edge("policy", "route")

    graph.add_conditional_edges("route", choose_route, _ROUTE_MAP)
    graph.add_edge("retrieval", "financial_data")
    graph.add_edge("financial_data", "calculation")
    graph.add_edge("calculation", "evidence")
    graph.add_edge("evidence", "claim")
    graph.add_edge("claim", "sentiment")
    graph.add_edge("sentiment", "debate")
    graph.add_edge("debate", "verification")

    graph.add_conditional_edges("verification", _after_verification, _VERIFY_MAP)
    graph.add_edge("answer", "audit")
    graph.add_edge("abstain", "audit")
    graph.add_edge("audit", END)

    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_research_qa"]