"""T606 Report Graph（§20 —— FROZEN 顺序）。

```text
START → load_research_run → load_evidence → load_calculations → assemble_claims
     → generate_sections → verify_sections → assemble_report → audit → END
```

确定性原则（AGENTS.md §3）：
- 各节点为确定性装载/组装（load_* / assemble_*），不调用 LLM；
- 前端平面数据经 ``research_run`` + 可选 ``evidences`` / ``calculations`` 输入注入，
  便于从 m01 持久化恢复研究现场后直接重放报告生成；
- ``verify_sections`` 复用 §23 规则。

治理短路（ADR-0017）：
- ``verify_sections`` 透传 ``policy_status``（原硬编码 ``None``，使 V009 永不触发）；
- 判 **FAIL** → ``abstain``（V010），不再产出报告正文；
- **ABSTAIN（V008 缺证据）不短路**，仍产出（空）报告。

独立状态 ``ReportState``（含 run_id / research_run / sections）。
"""
from __future__ import annotations

from typing import Any, TypedDict

from finsage.governance.verification import verify
from finsage.models.claims import ResearchAnswer
from finsage.observability.trace import uuid_str
from finsage.workflows.nodes import (
    NodeFn,
    WorkflowDeps,
    _make_claims,
    compute_answer_confidence,
    make_audit,
)


class ReportState(TypedDict, total=False):
    """§20 报告图运行状态。"""

    request_id: str
    trace_id: str
    run_id: str | None
    research_run: dict[str, Any] | None
    evidences: list[Any]
    calculations: list[Any]
    claims: list[Any]
    sections: list[str]
    policy_status: str | None
    verification_result: Any | None
    final_answer: ResearchAnswer | None
    error_code: str | None
    warnings: list[str]


# === load_research_run（§20）===
def make_load_research_run(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        # research_run 已由输入提供；此节点仅做兜底与 run_id 提取，不发明数据。
        run = state.get("research_run")
        if run is None:
            return {"run_id": state.get("run_id")}
        run_id = run.get("run_id") or state.get("run_id") or uuid_str()
        return {"research_run": run, "run_id": run_id}

    return _node


# === load_evidence（§20）===
def make_load_evidence(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        # 若调用方已在输入注入 evidences 则透传；否则为空（不猜测外部数据）。
        return {"evidences": list(state.get("evidences") or [])}

    return _node


# === load_calculations（§20）===
def make_load_calculations(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        return {"calculations": list(state.get("calculations") or [])}

    return _node


# === assemble_claims（§20）===
def make_assemble_claims(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        # 与 load_* 节点同口径：调用方已从持久化恢复研究现场并注入 claims 时原样透传
        # （§20 重放报告生成的场景），未注入时才由证据/计算确定性派生。
        existing = list(state.get("claims") or [])
        if existing:
            return {"claims": existing}
        claims = _make_claims(
            list(state.get("evidences") or []),
            list(state.get("calculations") or []),
        )
        return {"claims": claims}

    return _node


# === generate_sections（§20，确定性章节生成）===
def make_generate_sections(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        ev = list(state.get("evidences") or [])
        calc = list(state.get("calculations") or [])
        claims = list(state.get("claims") or [])
        sections: list[str] = [
            "## 摘要\n本文档基于证据与确定性计算自动生成。",
            f"## 证据（{len(ev)}）\n"
            + "\n".join(
                f"- [{getattr(e, 'id', i)}] {getattr(e, 'text', '')[:100]}"
                for i, e in enumerate(ev)
            ),
            f"## 计算（{len(calc)}）\n"
            + "\n".join(
                f"- {getattr(c, 'formula', '?')} = {getattr(c, 'output_value', '?')}"
                for c in calc
            ),
            f"## 论断（{len(claims)}）\n"
            + "\n".join(f"- {c.text}" for c in claims),
        ]
        return {"sections": sections}

    return _node


# === verify_sections（§20，复用 §23）===
def make_verify_sections(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        result = verify(
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            # ADR-0017：透传 policy_status（原硬编码 None 使 V009 永不触发）。
            policy_status=state.get("policy_status"),
        )
        update: dict = {"verification_result": result}
        if result.status == "FAIL":
            # V010：FAIL 不再组装报告（由条件边短路到 abstain）。
            update["error_code"] = "FIN-4101"
        return update

    return _node


def route_after_verify_sections(state: dict) -> str:
    """verify_sections 之后：仅 FAIL -> abstain（V010）；ABSTAIN/PASS 组装报告。"""
    status = getattr(state.get("verification_result"), "status", None)
    return "abstain" if status == "FAIL" else "assemble_report"


# === abstain（ADR-0017，V009/V010 短路）===
def make_report_abstention(deps: WorkflowDeps) -> NodeFn:
    """报告图专用弃权节点：只声明 ReportState 允许的字段。"""

    def _node(state: dict) -> dict:
        reason = state.get("error_code") or "verification_failed"
        warnings = list(state.get("warnings") or []) + [f"abstained:{reason}"]
        ans = ResearchAnswer(
            answer=f"本次请求无法产出可信研究报告（原因：{reason}）。",
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            confidence=0.0,
            warnings=warnings,
        )
        return {"final_answer": ans, "warnings": warnings}

    return _node


# === assemble_report（§20，确定性渲染）===
def make_assemble_report(deps: WorkflowDeps) -> NodeFn:
    def _node(state: dict) -> dict:
        sections = list(state.get("sections") or [])
        body = "\n\n".join(sections) if sections else "（无内容）"
        # P1 置信度接线（审计 §2.9）：六因素确定性推导，不硬编码 0.9。
        confidence = compute_answer_confidence(state)
        ans = ResearchAnswer(
            answer=body,
            claims=list(state.get("claims") or []),
            evidences=list(state.get("evidences") or []),
            calculations=list(state.get("calculations") or []),
            confidence=confidence,
            warnings=list(state.get("warnings") or []),
        )
        return {"final_answer": ans}

    return _node


def build_report(
    deps: WorkflowDeps | None = None,
    *,
    checkpointer: Any = None,
) -> Any:
    """装配 §20 Report 图。checkpointer 注入实现 T607 持久化。"""
    from langgraph.graph import END, START, StateGraph

    deps = deps or WorkflowDeps()

    graph = StateGraph(ReportState)
    graph.add_node("load_research_run", make_load_research_run(deps))
    graph.add_node("load_evidence", make_load_evidence(deps))
    graph.add_node("load_calculations", make_load_calculations(deps))
    graph.add_node("assemble_claims", make_assemble_claims(deps))
    graph.add_node("generate_sections", make_generate_sections(deps))
    graph.add_node("verify_sections", make_verify_sections(deps))
    graph.add_node("abstain", make_report_abstention(deps))
    graph.add_node("assemble_report", make_assemble_report(deps))
    graph.add_node("audit", make_audit(deps))

    graph.add_edge(START, "load_research_run")
    graph.add_edge("load_research_run", "load_evidence")
    graph.add_edge("load_evidence", "load_calculations")
    graph.add_edge("load_calculations", "assemble_claims")
    graph.add_edge("assemble_claims", "generate_sections")
    graph.add_edge("generate_sections", "verify_sections")
    graph.add_conditional_edges(
        "verify_sections",
        route_after_verify_sections,
        {"abstain": "abstain", "assemble_report": "assemble_report"},
    )
    graph.add_edge("abstain", "audit")
    graph.add_edge("assemble_report", "audit")
    graph.add_edge("audit", END)

    return graph.compile(checkpointer=checkpointer)


__all__ = [
    "ReportState",
    "build_report",
    "make_load_research_run",
    "make_load_evidence",
    "make_load_calculations",
    "make_assemble_claims",
    "make_generate_sections",
    "make_verify_sections",
    "make_report_abstention",
    "route_after_verify_sections",
    "make_assemble_report",
]