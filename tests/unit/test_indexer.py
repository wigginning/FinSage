"""ingestion/indexer 单元测试：Milvus 行映射（published_at_ts 缺失归 0）。"""

from __future__ import annotations

from finsage.ingestion.indexer import _row_for
from finsage.ingestion.models import Chunk, IndexedChunk


def _chunk() -> Chunk:
    return Chunk(
        document_id="doc-1",
        chunk_index=0,
        text="宁德时代 2024 年营收增长",
        page=1,
        section="第一章",
        text_hash="abc",
        text_length=12,
    )


def test_row_for_published_at_ts_none_defaults_zero():
    """published_at_ts 缺失/None 时归 0（INT64 不接受 nil）。"""
    ic = IndexedChunk(chunk=_chunk(), dense_vector=[0.1], sparse_vector={1: 0.2})
    row = _row_for(ic, doc_meta={"tenant_id": "t", "published_at": None})
    assert row["published_at_ts"] == 0
    assert row["tenant_id"] == "t"


def test_row_for_published_at_ts_preserved():
    """published_at_ts 有值时原样透传。"""
    ic = IndexedChunk(chunk=_chunk(), dense_vector=[0.1], sparse_vector={1: 0.2})
    row = _row_for(ic, doc_meta={"published_at_ts": 1728000000})
    assert row["published_at_ts"] == 1728000000
