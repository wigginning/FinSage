"""FinEval CaseExecutor 实现（ADR-0022）。

``CaseExecutor`` 契约（``evaluation/runner.py``）：``async def execute(case) -> Any``，
返回结果由对应 ``task_type`` 的 evaluator 评分（result 契约见 ``evaluators.py``）。

- ``DevEvalExecutor``：默认执行器。未接入真实图执行时返回 ``None``，各 evaluator 据此
  给出**真实**低分（不伪造分数，符合 AGENTS.md §10 诚实纪律）。生产部署经
  ``Deps.evaluation_executor`` 注入图驱动的 executor（环境依赖，类似检索/财务开关）。
"""
from __future__ import annotations

from finsage.evaluation.dataset import CaseSpec


class DevEvalExecutor:
    """开发/默认评估执行器：诚实占位，不伪造评估结果。

    返回 ``None`` 表示「该用例未被执行」；evaluator 据 result 契约给出真实评分
    （如 numeric 无数值 → 失分、abstention 未弃权 → 与「应作答」期望一致时得分）。
    真实端到端评测需注入图驱动的 CaseExecutor。
    """

    async def execute(self, case: CaseSpec) -> None:
        return None


def build_dev_executor() -> DevEvalExecutor:
    """构造默认开发执行器（供 Deps 装配）。"""
    return DevEvalExecutor()
