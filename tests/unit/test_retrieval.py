"""检索/重排/证据单测（T213，unit —— 不依赖 Milvus 服务）。

覆盖 §28.3：dense / sparse / fusion / rerank / metadata filter / citation 映射。
Milvus 通道召回以 FakeClient 模拟，聚焦融合权重、过滤表达式与证据映射的正确性。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finsage.models.sources import Evidence as EvidenceModel
from finsage.retrieval.evidence import build_evidence
from finsage.retrieval.models import ChunkHit
from finsage.retrieval.params import (
    DEFAULT_DENSE_WEIGHT,
    DEFAULT_SPARSE_WEIGHT,
    NUMERIC_DENSE_WEIGHT,
    NUMERIC_SPARSE_WEIGHT,
)
from finsage.retrieval.search import _build_filter, _fuse, hybrid_search


class FakeClient:
    """按 anns_field 路由返回预置召回的伪 MilvusClient（每行形如 Milvus 返回的 dict）。"""

    def __init__(self, dense: list[dict], sparse: list[dict]):
        self.dense = dense
        self.sparse = sparse

    def search(self, **kwargs):
        if kwargs["anns_field"] == "dense_vector":
            return [[dict(h) for h in self.dense]]
        return [[dict(h) for h in self.sparse]]


class FakeManager:
    def __init__(self, dense: list[dict], sparse: list[dict]):
        self.client = FakeClient(dense, sparse)


def _row(pk: str, text: str, **overrides) -> dict:
    entity = {
        "pk": pk,
        "document_id": "doc-1",
        "chunk_id": f"{pk}_c",
        "text": text,
        "page": 3,
        "section": "营收",
        "authority_tier": 8,
    }
    entity.update(overrides)
    return {"entity": entity, "distance": 0.5, "id": pk}


# ---- metadata filter ----


def test_build_filter_tenant_only():
    assert _build_filter(None, "tenant-x") == 'tenant_id == "tenant-x"'


def test_build_filter_custom_expr():
    expr = 'document_type == "annual" and report_period == "2024Q4"'
    assert _build_filter(expr, None) == f"({expr})"


def test_build_filter_compose_tenant_and_expr():
    """租户过滤与用户表达式必须正确 AND 组合（隔离 + 注入防御）。"""
    got = _build_filter('ticker == "AAPL"', "tenant-x")
    assert got == 'tenant_id == "tenant-x" and (ticker == "AAPL")'


def test_build_filter_empty():
    assert _build_filter(None, None) is None


def test_build_filter_escapes_tenant_id_quotes():
    """P2：租户 id 含引号时必须转义，阻断 Milvus expr 注入（越权检索）。"""
    got = _build_filter(None, 'tenant-a" or tenant_id == "victim')
    # 内部引号被转义为 \\"，无法逃逸出字符串字面量（注入面被消除）。
    assert got == 'tenant_id == "tenant-a\\" or tenant_id == \\"victim"'
    # 关键：过滤串中不存在「未转义」的引号边界 —— 转义后的串不再含裸 `: " ... " or ... "`。
    # 转义后每个内部引号前都有反斜杠。
    inner = got.split("==")[1].strip().strip('"')
    assert '\\"' in inner  # 内部引号均被转义


def test_escape_expr_str():
    from finsage.retrieval.schema import escape_expr_str

    assert escape_expr_str('a"b') == 'a\\"b'
    assert escape_expr_str("a\\b") == "a\\\\b"
    assert escape_expr_str("plain") == "plain"


# ---- dense / sparse 通道路由 ----


def test_hybrid_search_dense_sparse_collected():
    dense = [_row("a", "alpha"), _row("b", "beta", distance=0.9)]
    sparse = [_row("c", "gamma", distance=0.8), _row("a", "alpha", distance=0.7)]
    result = hybrid_search(
        FakeManager(dense, sparse),
        query="q",
        dense_vector=[0.1] * 8,
        sparse_vector={1: 0.5},
        candidate_k=10,
    )
    assert {h.pk for h in result.hits} == {"a", "b", "c"}
    assert result.dense_count == 2
    assert result.sparse_count == 2


def test_search_uses_search_params_not_param():
    """MilvusClient.search 用 search_params（pymilvus 3.0），非 param。"""
    captured: list[dict] = []

    class CaptureClient:
        def search(self, **kwargs):
            captured.append(kwargs)
            return [[dict(h) for h in [_row("a", "alpha")]]]

    class CaptureManager:
        client = CaptureClient()

    hybrid_search(
        CaptureManager(),
        query="q",
        dense_vector=[0.1] * 8,
        sparse_vector={1: 0.5},
        candidate_k=10,
    )
    assert captured, "应发起检索调用"
    for call in captured:
        assert "search_params" in call
        assert "param" not in call
    metrics = {call["search_params"]["metric_type"] for call in captured}
    assert metrics == {"COSINE", "IP"}


# ---- fusion 权重 ----


def test_fusion_semantic_weights_default():
    """默认权重 = 语义 0.7/0.3。"""
    hits = _fuse(
        [ChunkHit(pk="a", document_id="d", chunk_id="a_c", text="a", dense_score=1.0)],
        [ChunkHit(pk="b", document_id="d", chunk_id="b_c", text="b", sparse_score=1.0)],
        dense_weight=DEFAULT_DENSE_WEIGHT,
        sparse_weight=DEFAULT_SPARSE_WEIGHT,
    )
    by_pk = {h.pk: h for h in hits}
    # a 仅 dense 命中 → 0.7；b 仅 sparse 命中 → 0.3
    assert pytest.approx(by_pk["a"].fusion_score) == 0.7
    assert pytest.approx(by_pk["b"].fusion_score) == 0.3


def test_fusion_numeric_weights():
    """数值查询权重 0.4/0.6，sparse 主导。"""
    hits = _fuse(
        [ChunkHit(pk="a", document_id="d", chunk_id="a_c", text="a", dense_score=1.0)],
        [ChunkHit(pk="b", document_id="d", chunk_id="b_c", text="b", sparse_score=1.0)],
        dense_weight=NUMERIC_DENSE_WEIGHT,
        sparse_weight=NUMERIC_SPARSE_WEIGHT,
    )
    by_pk = {h.pk: h for h in hits}
    assert pytest.approx(by_pk["a"].fusion_score) == 0.4
    assert pytest.approx(by_pk["b"].fusion_score) == 0.6


def test_fusion_dedup_adds_both_channels():
    """同一 chunk 两通道命中须去重并累加。"""
    dense = ChunkHit(pk="a", document_id="d", chunk_id="a_c", text="a", dense_score=1.0)
    sparse = ChunkHit(pk="a", document_id="d", chunk_id="a_c", text="a", sparse_score=1.0)
    hits = _fuse([dense], [sparse], dense_weight=0.7, sparse_weight=0.3)
    assert len(hits) == 1
    assert pytest.approx(hits[0].fusion_score) == 1.0  # 0.7 + 0.3


def test_hybrid_search_no_candidates_raises():
    from finsage.exceptions import RetrievalError

    with pytest.raises(RetrievalError):
        hybrid_search(
            FakeManager([], []),
            query="q",
            dense_vector=[0.1] * 8,
            sparse_vector={1: 0.5},
        )


# ---- rerank 排序 ----


def test_rerank_priority_used_in_evidence():
    """命中携带 rerank_score 时，evidence 相关度取 rerank_score。"""
    hit = ChunkHit(
        pk="a",
        document_id="doc-1",
        chunk_id="a_c",
        text="文本",
        rerank_score=0.92,
        fusion_score=0.5,
    )
    ev = build_evidence(
        hit=hit,
        source_meta={"title": "年报", "provider": "upload"},
    )
    assert isinstance(ev, EvidenceModel)
    assert pytest.approx(ev.relevance_score) == 0.92


# ---- citation / evidence 映射（§28.3）----


def test_evidence_citation_mapping():
    hit = ChunkHit(
        pk="doc-1_0",
        document_id="doc-1",
        chunk_id="doc-1_0",
        text="净利润 1.2 亿元",
        page=7,
        section="财务摘要",
        authority_tier=9,
        dense_score=0.8,
    )
    ev = build_evidence(
        hit=hit,
        source_meta={
            "provider": "annual_report",
            "url": "https://ex.com/r.pdf",
            "title": "2024 年报",
            "published_at": datetime(2025, 3, 1, tzinfo=UTC),
        },
        retrieved_at=datetime(2025, 4, 1, tzinfo=UTC),
    )
    src = ev.source
    assert src.document_id == "doc-1"
    assert src.chunk_id == "doc-1_0"
    assert src.page == 7
    assert src.section == "财务摘要"
    assert src.url == "https://ex.com/r.pdf"
    assert src.authority_tier == 9
    assert ev.document_id == "doc-1"
    assert ev.chunk_id == "doc-1_0"
    assert ev.text == "净利润 1.2 亿元"


def test_evidence_authority_score_bound():
    """权威分须在 [0,1]。"""
    hit = ChunkHit(
        pk="a", document_id="d", chunk_id="a_c", text="t", authority_tier=10, dense_score=0.5
    )
    ev = build_evidence(hit=hit, source_meta={})
    assert 0.0 <= ev.authority_score <= 1.0