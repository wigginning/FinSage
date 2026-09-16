"""T210 Hybrid Search —— Dense+Sparse 权重融合检索（§6.4 / §21.3–21.4）。

流程：dense 通道召回 → sparse 通道召回 → 按 (dense_weight, sparse_weight) 融合
（同一 chunk 两通道分加权，去重；单通道命中则按该通道分加权）→ 排序产出 SearchResult。

说明：dense/sparse 分属不同 metric（COSINE≈[-1,1]、IP/BM25 无量纲），直接加权不可比，
故融合前各通道分在【该批召回内】做 min-max 归一化到 [0,1]，再按权重合成 —— 仅用于
跨通道排序，不改变各通道内部相对序。权重为默认语义 0.7/0.3，可经入参覆盖（Evaluation 用）。
"""

from __future__ import annotations

from finsage.exceptions import RetrievalError
from finsage.observability.logger import get_logger, io_point

from .client import MilvusClientManager
from .models import ChunkHit, SearchResult
from .params import DEFAULT_DENSE_WEIGHT, DEFAULT_SPARSE_WEIGHT, channel_k
from .schema import COLLECTION_NAME

logger = get_logger(__name__)

# 通道召回需回填到命中对象上的 Milvus 标量字段（§6.2 冻结 schema，无 section 字段）。
_FIELDS = [
    "pk",
    "document_id",
    "chunk_id",
    "text",
    "page",
    "authority_tier",
]


def _min_max(scores: list[float]) -> dict[float, float]:
    """把分数映射为 0..1（min-max）；全等分时归一为 1.0（该批唯一=最高）。"""
    if not scores:
        return {}
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return dict.fromkeys(set(scores), 1.0)
    return {s: (s - lo) / (hi - lo) for s in set(scores)}


def _row_to_hit(
    row: dict,
    *,
    dense_score: float | None = None,
    sparse_score: float | None = None,
) -> ChunkHit | None:
    """把一条 Milvus 命中行转成 ChunkHit；缺少身份字段则返回 None（丢弃该条）。

    ``document_id`` / ``chunk_id`` 是引用溯源的唯一凭据，缺失即无法生成可核验引用。
    此处宁可丢弃该条召回并告警，也**不回填空串**：空 id 会一路流到答案的 citation，
    产出"看起来有据、实际指向不存在文档"的引用，比少一条召回有害得多。
    """
    entity = row.get("entity") or {}
    document_id = entity.get("document_id")
    chunk_id = entity.get("chunk_id")
    if not document_id or not chunk_id:
        logger.warning(
            "retrieval.hit_missing_identity",
            extra={"extra": {"pk": entity.get("pk") or row.get("id")}},
        )
        return None
    return ChunkHit(
        pk=str(entity.get("pk", row["id"])),
        document_id=str(document_id),
        chunk_id=str(chunk_id),
        text=entity.get("text", ""),
        page=entity.get("page"),
        section=entity.get("section"),
        authority_tier=int(entity.get("authority_tier") or 0),
        dense_score=dense_score,
        sparse_score=sparse_score,
    )


def _build_filter(expr: str | None, tenant_id: str | None) -> str | None:
    """组合租户过滤与用户自定义标量过滤表达式（全部走 Milvus expr，严格防御注入）。"""
    from .schema import escape_expr_str

    parts: list[str] = []
    if tenant_id:
        parts.append(f'tenant_id == "{escape_expr_str(tenant_id)}"')
    if expr:
        parts.append(f"({expr})")
    return " and ".join(parts) if parts else None


@io_point("retrieval", "dense_search")
def _dense_search(
    manager: MilvusClientManager,
    *,
    dense_vector: list[float],
    candidate_k: int,
    expr: str | None,
) -> list[ChunkHit]:
    resp = manager.client.search(
        collection_name=COLLECTION_NAME,
        data=[dense_vector],
        anns_field="dense_vector",
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        limit=candidate_k,
        output_fields=_FIELDS,
        filter=expr,
    )
    hits: list[ChunkHit] = []
    for row in (resp[0] if resp else []):
        hit = _row_to_hit(row, dense_score=float(row["distance"]))
        if hit is not None:
            hits.append(hit)
    return hits


@io_point("retrieval", "sparse_search")
def _sparse_search(
    manager: MilvusClientManager,
    *,
    sparse_vector: dict,
    candidate_k: int,
    expr: str | None,
) -> list[ChunkHit]:
    resp = manager.client.search(
        collection_name=COLLECTION_NAME,
        data=[sparse_vector],
        anns_field="sparse_vector",
        search_params={"metric_type": "IP", "params": {"drop_ratio_search": 0.2}},
        limit=candidate_k,
        output_fields=_FIELDS,
        filter=expr,
    )
    hits: list[ChunkHit] = []
    for row in (resp[0] if resp else []):
        hit = _row_to_hit(row, sparse_score=float(row["distance"]))
        if hit is not None:
            hits.append(hit)
    return hits


def _fuse(
    dense_hits: list[ChunkHit],
    sparse_hits: list[ChunkHit],
    *,
    dense_weight: float,
    sparse_weight: float,
) -> list[ChunkHit]:
    """按权重融合两通道（返回顺序即 Score，非最终排序）。"""
    dense_norm = _min_max([h.dense_score for h in dense_hits if h.dense_score is not None])
    sparse_norm = _min_max([h.sparse_score for h in sparse_hits if h.sparse_score is not None])

    by_pk: dict[str, ChunkHit] = {}
    for hit in dense_hits:
        # 无该通道原始分的命中归一化分记 0（不参与该通道排序贡献）。
        norm = dense_norm.get(hit.dense_score, 0.0) if hit.dense_score is not None else 0.0
        hit.fusion_score = dense_weight * norm
        by_pk[hit.pk] = hit
    for hit in sparse_hits:
        norm = sparse_norm.get(hit.sparse_score, 0.0) if hit.sparse_score is not None else 0.0
        existing = by_pk.get(hit.pk)
        if existing is None:
            hit.fusion_score = sparse_weight * norm
            by_pk[hit.pk] = hit
        else:
            # 两通道都命中：累加该通道的加权归一化分。
            # existing 必来自上面的 dense 循环、fusion_score 已被赋值；or 0.0 仅为
            # 满足类型收敛，不掩盖真实缺失。
            existing.sparse_score = hit.sparse_score
            existing.fusion_score = (existing.fusion_score or 0.0) + sparse_weight * norm
    return list(by_pk.values())


@io_point("retrieval", "hybrid_search")
def hybrid_search(
    manager: MilvusClientManager,
    *,
    query: str = "",
    dense_vector: list[float],
    sparse_vector: dict,
    candidate_k: int = 50,
    dense_weight: float = DEFAULT_DENSE_WEIGHT,
    sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
    expr: str | None = None,
    tenant_id: str | None = None,
) -> SearchResult:
    """Dense+Sparse 混合检索，返回融合后按 fusion_score 降序的命中。"""
    expr = _build_filter(expr, tenant_id)
    dense_hits: list[ChunkHit] = []
    sparse_hits: list[ChunkHit] = []
    try:
        dense_hits = _dense_search(
            manager, dense_vector=dense_vector, candidate_k=channel_k(candidate_k), expr=expr
        )
    except RetrievalError:  # 通道级失败不阻断整体（策略见 No-Guess 边界）
        logger.warning("dense_channel_failed")
    try:
        sparse_hits = _sparse_search(
            manager, sparse_vector=sparse_vector, candidate_k=channel_k(candidate_k), expr=expr
        )
    except RetrievalError:
        logger.warning("sparse_channel_failed")

    if not dense_hits and not sparse_hits:
        raise RetrievalError("hybrid search returned no candidates")

    fused = _fuse(
        dense_hits,
        sparse_hits,
        dense_weight=dense_weight,
        sparse_weight=sparse_weight,
    )
    fused.sort(key=lambda h: h.fusion_score or 0.0, reverse=True)
    return SearchResult(
        query=query,
        hits=fused[:candidate_k],
        dense_weight=dense_weight,
        sparse_weight=sparse_weight,
        dense_count=len(dense_hits),
        sparse_count=len(sparse_hits),
    )


__all__ = ["hybrid_search", "ChunkHit", "SearchResult"]