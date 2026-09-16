"""Milvus 索引写入（T208/T209）。将索引分块持久化到 finsage_chunks。

只写 §6.2 固定的 15 个集合字段，pk 由 document_id + chunk_index 稳定合成
（确定性可复现，upsert 覆盖同一 pk 实现幂等重建）。
模型无关：dense/sparse 由 BGE3Embedder 产出的 IndexedChunk 承载。
"""

from __future__ import annotations

from finsage.exceptions import RetrievalError
from finsage.observability.logger import get_logger, io_point

from ..retrieval.client import MilvusClientManager
from ..retrieval.schema import COLLECTION_NAME
from .models import IndexedChunk

logger = get_logger(__name__)


# metadata 中可直接透传到 Milvus 标量字段的键集合（§6.2 + T206 产出）。
_SCALAR_FIELD_KEYS = (
    "tenant_id",
    "company",
    "ticker",
    "market",
    "document_type",
    "report_period",
    "published_at_ts",
    "authority_tier",
)


def _chunk_id(document_id: str, chunk_index: int) -> str:
    """稳定合成 chunk_id；单一来源，供 pk 与检索回填建档。"""
    return f"{document_id}_{chunk_index}"


def _row_for(ic: IndexedChunk, doc_meta: dict) -> dict:
    """把单个 IndexedChunk 映射为 Milvus 行（§6.2 固定字段）。"""
    chunk = ic.chunk
    row: dict = {
        "pk": _chunk_id(chunk.document_id, chunk.chunk_index),
        "document_id": chunk.document_id,
        "chunk_id": _chunk_id(chunk.document_id, chunk.chunk_index),
        "text": chunk.text,
        "dense_vector": ic.dense_vector,
        "sparse_vector": ic.sparse_vector,
        "page": chunk.page,
    }
    for key in _SCALAR_FIELD_KEYS:
        value = doc_meta.get(key)
        # §6.2 标量字段在 Milvus 中不可为 nil：
        # - INT64（published_at_ts）缺失诚实归 0（未知时间）；
        # - VARCHAR 字段（company/ticker/market/document_type/report_period/tenant_id）
        #   缺失归空串。避免上游可选元数据为 None 时 upsert 失败（真实上传链路常见）。
        if value is None:
            value = 0 if key == "published_at_ts" else ""
        row[key] = value
    return row


@io_point("ingestion", "milvus_upsert_chunks")
def index_chunks(
    manager: MilvusClientManager,
    indexed_chunks: list[IndexedChunk],
    *,
    doc_meta: dict,
) -> int:
    """将索引分块批量 upsert 到 finsage_chunks；返回写入条数。

    幂等：pk 固定，重复调用覆盖同 document 的 chunk 记录。
    """
    if not indexed_chunks:
        return 0

    rows = [_row_for(ic, doc_meta) for ic in indexed_chunks]
    try:
        resp = manager.client.upsert(collection_name=COLLECTION_NAME, data=rows)
    except Exception as exc:  # noqa: BLE001 - 底层驱动异常统一归检索错误
        raise RetrievalError(f"milvus upsert failed: {type(exc).__name__}") from exc

    count = int(resp.get("upsert_count", len(rows)))
    logger.info(
        "indexed",
        extra={
            "extra": {
                "collection": COLLECTION_NAME,
                "document_id": rows[0].get("document_id"),
                "expected": len(rows),
                "upserted": count,
            }
        },
    )
    return count