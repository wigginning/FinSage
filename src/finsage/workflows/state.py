"""§15 FROZEN LangGraph State（m06 T601）。

``ResearchState`` 逐字段对齐规格 §15。约束：
- Node 只能修改自己拥有的字段；
- 禁止任意节点覆盖 final_answer（除 answer_node）；
- 禁止在 state 中存储 secret / 未脱敏 API key。

LangGraph 在运行时经 ``get_type_hints`` 求值注解（``from __future__ import annotations``
仅把注解转成字符串，仍需在求值时可解析），故此处必须做真实 import。被引用的模型模块
均不反向依赖 ``workflows.state``，不会形成循环导入。
"""
from __future__ import annotations

from typing import TypedDict

from finsage.financial.models import Calculation
from finsage.governance.models import VerificationResult
from finsage.models.claims import Claim, ResearchAnswer, SentimentSummary
from finsage.models.debate import DebateResult
from finsage.models.entities import Entity
from finsage.models.planning import RetrievalPlan
from finsage.models.sources import Evidence
from finsage.providers.finance.domain import FinancialMetric


class ResearchState(TypedDict, total=False):
    """§15 LangGraph State（所有键可选，便于各节点增量更新）。"""

    # 标识
    request_id: str
    trace_id: str
    task_id: str
    # P0 权限：请求身份租户（透传到检索做跨租户隔离）
    tenant_id: str | None

    # 查询理解
    query: str
    normalized_query: str | None
    intent: str | None
    entities: list[Entity]
    # P0 会话记忆：历史消息（role/content 列表），供 LLM 续聊上下文。
    chat_history: list[dict[str, str]]

    # 政策门
    policy_status: str | None
    warnings: list[str]

    # 检索与证据
    retrieval_plan: RetrievalPlan | None
    evidences: list[Evidence]
    financial_data: list[FinancialMetric]
    calculations: list[Calculation]

    # 论断 / 草稿 / 校验
    claims: list[Claim]
    draft_answer: str | None
    verification_result: VerificationResult | None

    # 多空辩论（ADR-0009）
    debate_result: DebateResult | None

    # 证据集情绪聚合（ADR-0011 / ADR-0018，规则法，calibrated=False）
    sentiment_summary: SentimentSummary | None

    # 最终
    confidence: float | None
    final_answer: ResearchAnswer | None

    # 错误
    error_code: str | None


__all__ = ["ResearchState"]