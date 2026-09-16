"""T605 Due Diligence Graph（§19 —— FROZEN 阶段机）。

```text
START → WARMUP → COMPANY_PROFILE → BUSINESS_MODEL → FINANCIALS
     → COMPETITION → RISK → RED_FLAGS → FOLLOW_UP → REPORT
     → VERIFICATION → AUDIT → END
```

确定性原则：
- 各阶段节点为确定性模板，把该阶段的分析片段写入 ``dossier[<阶段>]`` 并追加到 ``findings``；
- ``REPORT`` 将各阶段片段确定性拼接为范本报告（final_answer）；
- ``VERIFICATION`` 复用 §23 规则对论断/证据/计算做校验；
- 不调用 LLM，不跨节点覆盖别的字段。

治理短路（ADR-0017）：
- ``POLICY`` 位于阶段机之前，``block`` → ``ABSTAIN``（V009）；
- ``VERIFICATION`` 判 **FAIL** → ``ABSTAIN``（V010），不再产出报告正文；
- **ABSTAIN（V008 缺证据）不短路**，仍保留范本报告（§23 中 V008 与 V010 是两条路径）；
- 短路路径同样落 ``AUDIT``（§25）。

状态为独立 ``DueDiligenceState``（承载 dossier / findings，ResearchState 不含这些字段）。
"""
from __future__ import annotations

from typing import Any, TypedDict

from finsage.governance.verification import verify
from finsage.models.claims import ResearchAnswer
from finsage.workflows.nodes import (
    NodeFn,
    WorkflowDeps,
    compute_answer_confidence,
    make_abstention,
    make_audit,
    make_policy,
)

# §19 阶段顺序 —— FROZEN。禁止增删或调序。
DUE_DILIGENCE_PHASES: tuple[str, ...] = (
    "WARMUP",
    "COMPANY_PROFILE",
    "BUSINESS_MODEL",
    "FINANCIALS",
    "COMPETITION",
    "RISK",
    "RED_FLAGS",
    "FOLLOW_UP",
)


class DueDiligenceState(TypedDict, total=False):
    """§19 尽调图运行状态。"""

    request_id: str
    trace_id: str
    task_id: str
    query: str
    entities: list[Any]
    policy_status: str | None
    warnings: list[str]
    evidences: list[Any]
    calculations: list[Any]
    findings: list[str]
    dossier: dict[str, str]
    report: str | None
    claims: list[Any]
    verification_result: Any | None
    confidence: float | None
    final_answer: ResearchAnswer | None
    error_code: str | None


# §19 各阶段的确定性分析模板。
_PHASE_TEMPLATES: dict[str, str] = {
    "WARMUP": "启动尽调：目标为 {company}。",
    "COMPANY_PROFILE": "公司概况：{company} 主营业务与组织形态信息待外部证据补全。",
    "BUSINESS_MODEL": "商业模式：以证据为基础归纳盈利模式与现金循环。",
    "FINANCIALS": "财务表现：结合确定性财务计算输出营收/利润与比值指标。",
    "COMPETITION": "竞争格局：比较可比公司关键指标（依据证据）。",
    "RISK": "风险：识别政策、市场、经营与合规风险（依据证据）。",
    "RED_FLAGS": "红旗：标记证据缺失或相互冲突的异常点。",
    "FOLLOW_UP": "后续事项：列出需进一步核实的清单。",
}


def _company(state: dict) -> str:
    for e in list(state.get("entities") or []):
        if getattr(e, "type", None) in ("ticker", "company"):
            return getattr(e, "value", "标的")
    return "标的"


def make_phase(phase: str) -> NodeFn:
    """生成某一尽调阶段的确定性节点：写 dossier[phase] 并追加 finding。"""
    template = _PHASE_TEMPLATES[phase]

    def _node(state: dict) -> dict:
        text = template.format(company=_company(state))
        dossier = dict(state.get("dossier") or {})
        dossier[phase] = text
        findings = list(state.get("findings") or []) + [text]
        return {"dossier": dossier, "findings": findings}

    return _node


# === REPORT（§19，确定性组装范本报告）===
def make_due_diligence_report(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        dossier = state.get("dossier") or {}
        lines = [dossier[p] for p in DUE_DILIGENCE_PHASES if dossier.get(p)]
        report = "\n".join(lines) or "尽调报告：目前无可用信息。"
        # §19 顺序为 REPORT → VERIFICATION，置信度需要 verification 门控（§24），
        # 因此在此先做一次**确定性预校验**：verify() 是纯函数，与后续 VERIFICATION
        # 节点的输入一致，结果必然相同，不产生分歧，也不引入旁路。
        provisional = verify(
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            policy_status=state.get("policy_status"),
        )
        probe = dict(state)
        probe["verification_result"] = provisional
        # P1 置信度接线（审计 §2.9）：六因素确定性推导，不硬编码 0.9。
        confidence = compute_answer_confidence(probe)
        ans = ResearchAnswer(
            answer=report,
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            confidence=confidence,
            warnings=list(state.get("warnings") or []),
        )
        return {
            "report": report,
            "final_answer": ans,
            "confidence": confidence,
            "verification_result": provisional,
        }

    return _node


# === VERIFICATION（§19，复用 §23 规则）===
def make_due_diligence_verification(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        result = verify(
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            policy_status=state.get("policy_status"),
        )
        update: dict = {"verification_result": result}
        if result.status == "FAIL":
            # V010：FAIL 不再保留报告（由条件边短路到 ABSTAIN）。
            update["error_code"] = "FIN-4101"
        return update

    return _node


def route_after_policy(state: dict) -> str:
    """POLICY 之后：block -> ABSTAIN（V009），否则进入八阶段机。"""
    if state.get("policy_status") == "block" or state.get("error_code"):
        return "ABSTAIN"
    return "WARMUP"


def route_after_verification(state: dict) -> str:
    """VERIFICATION 之后：仅 FAIL -> ABSTAIN（V010）；ABSTAIN/PASS 保留报告。"""
    status = getattr(state.get("verification_result"), "status", None)
    return "ABSTAIN" if status == "FAIL" else "AUDIT"


def build_due_diligence(
    deps: WorkflowDeps | None = None,
    *,
    checkpointer: Any = None,
) -> Any:
    """装配 §19 Due Diligence 图（含 ADR-0017 治理短路）。

    checkpointer 注入实现 T607 持久化。
    """
    from langgraph.graph import END, START, StateGraph

    deps = deps or WorkflowDeps()

    graph = StateGraph(DueDiligenceState)
    # 治理节点（ADR-0017）：位于阶段机之前/之后，不改变 DUE_DILIGENCE_PHASES 顺序。
    graph.add_node("POLICY", make_policy(deps))
    for phase in DUE_DILIGENCE_PHASES:
        graph.add_node(phase, make_phase(phase))
    graph.add_node("REPORT", make_due_diligence_report(deps))
    graph.add_node("VERIFICATION", make_due_diligence_verification(deps))
    graph.add_node("ABSTAIN", make_abstention(deps))
    graph.add_node("AUDIT", make_audit(deps))

    graph.add_edge(START, "POLICY")
    graph.add_conditional_edges(
        "POLICY",
        route_after_policy,
        {"WARMUP": "WARMUP", "ABSTAIN": "ABSTAIN"},
    )
    prev: Any = "WARMUP"
    for phase in DUE_DILIGENCE_PHASES[1:]:
        graph.add_edge(prev, phase)
        prev = phase
    graph.add_edge(prev, "REPORT")
    graph.add_edge("REPORT", "VERIFICATION")
    graph.add_conditional_edges(
        "VERIFICATION",
        route_after_verification,
        {"AUDIT": "AUDIT", "ABSTAIN": "ABSTAIN"},
    )
    graph.add_edge("ABSTAIN", "AUDIT")
    graph.add_edge("AUDIT", END)

    return graph.compile(checkpointer=checkpointer)


__all__ = [
    "DueDiligenceState",
    "DUE_DILIGENCE_PHASES",
    "build_due_diligence",
    "make_phase",
    "make_due_diligence_report",
    "make_due_diligence_verification",
    "route_after_policy",
    "route_after_verification",
]