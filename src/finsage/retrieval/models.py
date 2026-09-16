"""检索域结构体（T210/T211 内部传输对象）。

dense/sparse 通道召回与融合结果，作为跨层接口的类型契约（AGENTS.md §2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChunkHit:
    """单条检索召回片段（融合前/后的统一载体）。"""

    pk: str
    document_id: str
    chunk_id: str
    text: str
    page: int | None = None
    section: str | None = None
    authority_tier: int = 1
    # 各通道原始分（dense_score / sparse_score）。
    dense_score: float | None = None
    sparse_score: float | None = None
    # 融合后分数 / 重排后分数。
    fusion_score: float | None = None
    rerank_score: float | None = None


@dataclass
class SearchResult:
    """混合检索产出：按分排序的命中 + 使用的权重/通道计数。"""

    query: str
    hits: list[ChunkHit] = field(default_factory=list)
    dense_weight: float = 0.0
    sparse_weight: float = 0.0
    dense_count: int = 0
    sparse_count: int = 0