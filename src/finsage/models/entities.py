"""Query 解析域模型（§4.1 Entity + §16.3 Intent / §16.6 Route —— FROZEN 枚举）。

Entity 字段完全对齐 §4.1；Intent 取值对齐 §16.3/§21.1；Route 取值对齐 §16.6。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# §4.1 Entity.type
EntityType = Literal["company", "ticker", "person", "industry", "document", "metric"]

# §16.3 / §21.1 Query Intent
IntentType = Literal[
    "FACT",
    "NUMERIC",
    "COMPARISON",
    "EXPLANATION",
    "RESEARCH",
    "MULTI_HOP",
    "DOCUMENT_LOOKUP",
    "REALTIME",
    "UNKNOWN",
]

# §16.6 Route
RouteChoice = Literal["RAG", "FINANCIAL_MCP", "CALCULATOR", "COMBINED", "ABSTAIN"]


class Entity(BaseModel):
    """查询实体（§4.1）。"""

    type: EntityType
    value: str
    normalized_value: str | None = None
    market: str | None = None


__all__ = ["Entity", "EntityType", "IntentType", "RouteChoice"]