"""C-8 FinEval 真实数据跑分（单次、低频、合规）。

接线真实 research_qa 工作流：真实 Provider Registry + 真实 LLM（build_llm_provider，
按 .env 配置路由）。对 FinEval 基准的可离线子集（abstention / provider_reliability，
以及有可能命中 Registry 真实数据的 numeric 用例）执行并打印指标。

边界说明（No-Guess / Honesty，AGENTS.md §10）：
- Milvus 集合不存在（无种子语料），retrieval / citation 用例无法真实召回 → 本脚本
  不跑这两类，避免编造命中。真实召回需先建集并灌入语料。
- numeric 依赖真实基本面接口；AKShare/其他源的字段映射标『待实测校准』，命中即
  为真实数据校准证据，未命中则如实记录，不伪装。
- 频控：每个 Provider/模型单次或少量请求，不批量抓取。
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any

from finsage.agents.research_qa.graph import build_research_qa
from finsage.evaluation import (
    TASK_ABSTENTION,
    TASK_PROVIDER,
    BenchmarkRunner,
    CaseSpec,
    build_benchmark,
    collect_metadata,
)
from finsage.providers.finance import build_registry
from finsage.providers.llm import build_llm_provider
from finsage.workflows.nodes import WorkflowDeps


@dataclass
class _RealDeps:
    """真实依赖容器：Registry + LLM Provider + research_qa 图。"""

    registry: Any = field(default_factory=build_registry)
    llm: Any = field(default_factory=build_llm_provider)
    graph: Any = None

    def __post_init__(self) -> None:
        graph_deps = WorkflowDeps(llm=self.llm)
        self.graph = build_research_qa(graph_deps)


class RealCaseExecutor:
    """真实执行器：把 FinEval 用例映射到 research_qa 图 / Registry 的真实产出。"""

    def __init__(self, deps: _RealDeps) -> None:
        self._deps = deps

    async def _run_graph(self, query: str) -> dict:
        return await self._deps.graph.ainvoke(
            {"query": query, "request_id": "fineval", "trace_id": "fineval"}
        )

    async def execute(self, case: CaseSpec):  # noqa: ANN201
        if case.task_type == TASK_PROVIDER:
            return await self._provider_result(case)
        # abstention / numeric：走真实 research_qa 图
        out = await self._run_graph(case.query)
        return self._graph_result(case, out)

    # ---- provider_reliability：Registry 真实连续取数（轻量直连 tencent，避免全市场抓取）----

    async def _provider_result(self, case: CaseSpec) -> dict:
        tencent = self._deps.registry.get("tencent")
        if tencent is None:  # 无轻量源，退化为 registry.invoke 单次（No-Guess，记录 attempt）
            return await self._provider_failover()
        attempts = 3
        successes = 0
        for _ in range(attempts):
            try:
                q = await tencent.get_quote("000001", "CN.SZ")
                if q is not None:
                    successes += 1
            except Exception:  # noqa: BLE001 - 计数失败，不伪装
                continue
        return {"attempts": attempts, "successes": successes}

    async def _provider_failover(self) -> dict:
        attempts = 2
        successes = 0
        for _ in range(attempts):
            try:
                await self._deps.registry.invoke(
                    lambda p: p.get_quote("000001", "CN.SZ"),
                    operation="quote",
                    market="CN",
                )
                successes += 1
            except Exception:  # noqa: BLE001 - 计数失败，不伪装
                continue
        return {"attempts": attempts, "successes": successes}

    # ---- 图结果 -> evaluator 契约 ----

    @staticmethod
    def _graph_result(case: CaseSpec, out: dict) -> dict:
        err = out.get("error_code")
        conf = out.get("confidence")
        if case.task_type == TASK_ABSTENTION:
            abstained = bool(err) or (conf is not None and float(conf) < 0.45)
            return {"abstained": abstained, "confidence_bucket": "ABSTAIN" if abstained else "LOW"}
        return {}


async def _main() -> None:
    deps = _RealDeps()
    if deps.llm is None:
        print("WARN: 未配置真实 LLM，将使用 Dummy（结果仅验证框架）。")
    reported = build_llm_provider()
    print(f"llm provider: {type(reported).__name__}")

    bench = build_benchmark()
    subset = []
    for case in bench.cases:
        if case.task_type == TASK_PROVIDER:
            subset.append(case)
        elif case.task_type == TASK_ABSTENTION and case.expected.get("expect_abstention"):
            # 无 Milvus 语料：仅验证『本应弃权』的真实弃权行为，避免无据作答
            subset.append(case)
        # numeric/retrieval/citation 需真实语料或精确基本面，无语料时跳过（No-Guess）
    from finsage.evaluation import build_dataset

    spec = build_dataset(name="finsage-real-subset", version="v3.4-c8", cases=subset)

    meta = collect_metadata(model_name=getattr(deps.llm, "_model", "unknown"))
    runner = BenchmarkRunner(RealCaseExecutor(deps), metadata=meta)
    report = await runner.run(spec)
    print(f"\nreal subset: {report.total} cases, passed {report.passed}, "
          f"pass_rate={report.pass_rate}, avg_score={report.avg_score}")
    for task_type, m in sorted(report.metrics["per_type"].items()):
        print(f"  [{task_type}] total={m['total']} passed={m['passed']} "
              f"pass_rate={m['pass_rate']} avg={m['avg_score']}")

    # 逐条明细（真实证据锚点）
    print("\n-- detail --")
    for o in report.outcomes:
        print(f"  {o.task_type:10s} pass={str(o.passed):5s} score={o.score:.3f} {o.details}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)