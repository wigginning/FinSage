"""index_chunks 对可选标量元数据 None 的容忍（真实上传链路常见）。

回归：此前 doc_meta 中 company/ticker/market/document_type/report_period 为 None 时，
upsert 会因 Milvus VARCHAR 字段不可为 nil 而抛 FIN-3001。现应诚实归空串；
published_at_ts（INT64）缺失仍归 0，与既有约定一致。
"""
from __future__ import annotations

from finsage.ingestion import index_chunks
from finsage.ingestion.models import Chunk, IndexedChunk


class _FakeClient:
    def __init__(self) -> None:
        self.captured = None

    def upsert(self, *, collection_name, data):
        self.captured = (collection_name, data)
        return {"upsert_count": len(data)}


class _FakeManager:
    def __init__(self) -> None:
        self.client = _FakeClient()


def _chunk(document_id: str = "d1", chunk_index: int = 0) -> Chunk:
    return Chunk(
        document_id=document_id,
        chunk_index=chunk_index,
        text="hello world",
        page=1,
        section=None,
        text_hash="h",
        text_length=11,
    )


def _ic(chunk: Chunk) -> IndexedChunk:
    return IndexedChunk(chunk=chunk, dense_vector=[0.1, 0.2], sparse_vector={1: 0.5})


_BASE_META = {
    "tenant_id": "t1",
    "company": None,
    "ticker": None,
    "market": None,
    "document_type": None,
    "report_period": None,
    "published_at_ts": None,
    "authority_tier": 1,
}


def test_none_varchar_fields_become_empty_string():
    mgr = _FakeManager()
    n = index_chunks(mgr, [_ic(_chunk())], doc_meta=dict(_BASE_META))
    assert n == 1
    row = mgr.client.captured[1][0]
    assert row["company"] == ""
    assert row["ticker"] == ""
    assert row["market"] == ""
    assert row["document_type"] == ""
    assert row["report_period"] == ""
    assert row["tenant_id"] == "t1"
    assert row["published_at_ts"] == 0
    assert row["authority_tier"] == 1


def test_present_values_passthrough():
    mgr = _FakeManager()
    meta = {
        "tenant_id": "t1",
        "company": "CATL",
        "ticker": "300750",
        "market": "A",
        "document_type": "report",
        "report_period": "2024",
        "published_at_ts": 1700000000,
        "authority_tier": 2,
    }
    index_chunks(mgr, [_ic(_chunk())], doc_meta=meta)
    row = mgr.client.captured[1][0]
    assert row["company"] == "CATL"
    assert row["report_period"] == "2024"
    assert row["published_at_ts"] == 1700000000
    assert row["authority_tier"] == 2
