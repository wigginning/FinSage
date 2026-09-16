"""Answer / Claim 域模型（§4.4 Claim / §4.8 ResearchAnswer —— FROZEN）。

结构逐字段对齐规格 §4.4 / §4.8。ResearchAnswer 内的 Evidence/Calculation 为
非强类型字段（``Annotated`` 仅作说明），运行时由上层节点注入真实对象。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# §4.4 Claim.claim_type
ClaimType = Literal["fact", "numeric", "comparison", "explanation", "research", "risk"]


class Claim(BaseModel):
    """由 Evidence / Calculation 生成的论断（§4.4）。"""

    id: str
    text: str
    claim_type: ClaimType
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    verified: bool = False


class SentimentSummary(BaseModel):
    """证据集情绪聚合（ADR-0011 / ADR-0018）。

    ``calibrated=False`` 是硬约束：规则法关键词打分未在真实语料上校准，
    **不得**当作权威情绪结论对外呈现（AGENTS.md §10）。
    """

    analyzed: int = Field(default=0, description="参与打分的证据条数")
    positive: int = Field(default=0, description="判为利好的条数")
    neutral: int = Field(default=0, description="判为中性的条数")
    negative: int = Field(default=0, description="判为利空的条数")
    mean_score: float = Field(default=0.0, ge=-1, le=1, description="情绪分均值")
    method: str = "keyword_rule_based"
    calibrated: bool = False


class ResearchAnswer(BaseModel):
    """结构化最终答案（§4.8）。"""

    answer: str
    claims: list[Claim] = Field(default_factory=list)
    evidences: list[Any] = Field(default_factory=list)
    calculations: list[Any] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    audit_id: str = ""
    # 多空分歧度（ADR-0009）：0..1，None 表示未运行辩论节点。
    disagreement: float | None = Field(default=None, ge=0, le=1)
    # 证据集情绪聚合（ADR-0018）：None 表示未做情绪富化；calibrated 恒为 False。
    sentiment_summary: SentimentSummary | None = None


__all__ = ["Claim", "ClaimType", "SentimentSummary", "ResearchAnswer"]