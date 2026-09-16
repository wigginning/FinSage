"""retrieval 域：Milvus 混合检索（T2..）、重排、Evidence 产出。"""

from .client import MilvusClientManager
from .evidence import build_evidence, persist_evidence
from .models import ChunkHit, SearchResult
from .params import (
    CANDIDATE_K,
    DEFAULT_DENSE_WEIGHT,
    DEFAULT_SPARSE_WEIGHT,
    NUMERIC_DENSE_WEIGHT,
    NUMERIC_SPARSE_WEIGHT,
    RERANK_K,
)
from .rerank import BGEReranker
from .schema import COLLECTION_NAME, ensure_collection
from .search import hybrid_search

__all__ = [
    "MilvusClientManager",
    "build_evidence",
    "persist_evidence",
    "ChunkHit",
    "SearchResult",
    "CANDIDATE_K",
    "DEFAULT_DENSE_WEIGHT",
    "DEFAULT_SPARSE_WEIGHT",
    "NUMERIC_DENSE_WEIGHT",
    "NUMERIC_SPARSE_WEIGHT",
    "RERANK_K",
    "BGEReranker",
    "COLLECTION_NAME",
    "ensure_collection",
    "hybrid_search",
]