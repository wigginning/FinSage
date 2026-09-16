"""多空辩论域模型（ADR-0009 —— F4 不确定性显式化）。

``DebateArgument`` 是 bull/bear 子 agent 产出的单条论点：LLM 只生成 ``text``，
``evidence_ids`` / ``confidence`` 由确定性代码绑定（AGENTS.md §3）。``DebateResult``
是确定性仲裁的产物，``disagreement`` 为多空分歧度（0..1），``verdict`` 由聚合
置信度决定，绝不调用 LLM 裁决。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 论点立场。
DebateSide = Literal["bull", "bear"]

# 仲裁结论。
DebateVerdict = Literal["bull", "bear", "balanced", "insufficient"]


class DebateArgument(BaseModel):
    """单条多空论点（§ADR-0009）。"""

    side: DebateSide
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class DebateResult(BaseModel):
    """确定性仲裁结果（§ADR-0009）。"""

    bull_arguments: list[DebateArgument] = Field(default_factory=list)
    bear_arguments: list[DebateArgument] = Field(default_factory=list)
    # 多空分歧度：0 = 无分歧（无空方反对），1 = 完全分歧（证据集不相交）。
    disagreement: float = Field(ge=0, le=1)
    verdict: DebateVerdict = "insufficient"


class DebateArgumentDraft(BaseModel):
    """LLM 结构化输出的论点草稿（ADR-0012，不含 side，由调用方补）。"""

    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class DebateArgumentsResponse(BaseModel):
    """LLM 结构化输出的论点列表（ADR-0012）。"""

    arguments: list[DebateArgumentDraft] = Field(default_factory=list)


__all__ = [
    "DebateArgument",
    "DebateResult",
    "DebateSide",
    "DebateVerdict",
    "DebateArgumentDraft",
    "DebateArgumentsResponse",
]
