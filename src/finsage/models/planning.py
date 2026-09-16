"""检索计划域模型（§16.7 / §21 —— m06 引入，供 research 计划与 retrieval_node 使用）。

RetrievalPlan 描述一次检索的静态配置：候选 K / 重排 K / 融合权重 / 过滤表达式 / 租户。
初始权重来自 §21.3–21.4 冻结默认值（可经配置覆盖，Evaluation 阶段校准）。
"""
from __future__ import annotations

from pydantic import BaseModel


class RetrievalPlan(BaseModel):
    """检索计划（§16.7）。"""

    candidate_k: int = 50
    rerank_k: int = 10
    dense_weight: float = 0.7
    sparse_weight: float = 0.3
    expr: str | None = None
    tenant_id: str | None = None


__all__ = ["RetrievalPlan"]