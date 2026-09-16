"""检索来源与证据领域模型（规格 §4.2 / §4.3 —— FROZEN）。

实现与规格的 Pydantic 结构逐字段一致，禁止增删字段。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """证据来源引用（§4.2）。"""

    source_id: str
    provider: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    title: str
    page: int | None = None
    section: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    authority_tier: int


class Evidence(BaseModel):
    """金融回答证据（§4.3）。"""

    id: str
    document_id: str
    chunk_id: str
    source: SourceRef
    text: str
    relevance_score: float = Field(ge=0, le=1)
    authority_score: float = Field(ge=0, le=1)