"""摄取（ingestion）域结构体与常量。

documents / document_chunks 的持久化模型位于 persistence.models.rag；
此处定义摄取流水线（解析→分块→元数据→嵌入→索引）内部使用的传输对象，
为跨层接口，含类型契约（AGENTS.md §2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    """文档单页（PDF parser 产出）。"""

    number: int  # 页码，从 1 起
    text: str
    section: str | None = None  # 章节标题（提取到才有）


@dataclass
class ParsedDocument:
    """解析后的文档（含文本与元数据）。"""

    title: str
    source_type: str  # upload / web / financial
    pages: list[Page] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # company/ticker/market 等（T206）


@dataclass
class Chunk:
    """单个分块（T205）。"""

    document_id: str
    chunk_index: int
    text: str
    page: int | None
    section: str | None
    text_hash: str  # SHA256(text)
    text_length: int


@dataclass
class IndexedChunk:
    """待写入 Milvus 的分块（含密集/稀疏向量，T208/T209）。"""

    chunk: Chunk
    dense_vector: list[float]
    sparse_vector: dict  # {token_id(int): weight(float)}


# 检索/重排候选数（§6.3 契约，可经配置覆盖，参见 retrieval.params）。
CANDIDATE_K = 50
RERANK_K = 10