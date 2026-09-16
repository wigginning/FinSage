"""T212 Evidence 产出与持久化（§4.2/§4.3）。

从检索命中（ChunkHit）映射为领域 Evidence 对象（pydantic §4.3），
并经 EvidenceRepository 落 evidence 表（§5.10，见 persistence/models/rag.py）。

引用映射（citation）：Evidence.source 携带 document_id / chunk_id / page / section /
authority_tier / url / provider 等，保证可溯源性（AGENTS.md §5）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from finsage.models.sources import Evidence as EvidenceModel
from finsage.models.sources import SourceRef
from finsage.observability.logger import get_logger, io_point
from finsage.persistence.models.rag import Evidence as EvidenceRow
from finsage.persistence.repositories.research import EvidenceRepository

from .models import ChunkHit

logger = get_logger(__name__)


def _authority_score(authority_tier: int) -> float:
    """权威层级 -> [0,1] 权威分（层级越大越权威；层级<=0 视为最低）。"""
    return min(1.0, max(0.0, authority_tier / 10.0))


def build_evidence(
    *,
    hit: ChunkHit,
    source_meta: dict,
    retrieved_at: datetime | None = None,
) -> EvidenceModel:
    """把一条 ChunkHit 映射为 Evidence 对象（§4.3，via citation 映射）。"""
    source = SourceRef(
        source_id=f"{hit.document_id}_{hit.chunk_id}",
        provider=source_meta.get("provider"),
        document_id=hit.document_id,
        chunk_id=hit.chunk_id,
        url=source_meta.get("url"),
        title=source_meta.get("title") or hit.document_id,
        page=hit.page,
        section=hit.section,
        published_at=source_meta.get("published_at"),
        retrieved_at=retrieved_at or datetime.now(UTC),
        authority_tier=hit.authority_tier,
    )
    # 相关度优先取重排分，其次融合分，最后任一通道分（归一化到 0..1）。
    if hit.rerank_score is not None:
        relevance = min(1.0, max(0.0, float(hit.rerank_score)))
    elif hit.fusion_score is not None:
        relevance = min(1.0, max(0.0, float(hit.fusion_score)))
    else:
        raw = hit.dense_score if hit.dense_score is not None else hit.sparse_score
        relevance = min(1.0, max(0.0, float(raw or 0.0)))

    return EvidenceModel(
        id=f"{hit.document_id}_{hit.chunk_id}",
        document_id=hit.document_id,
        chunk_id=hit.chunk_id,
        source=source,
        text=hit.text,
        relevance_score=round(relevance, 6),
        authority_score=round(_authority_score(hit.authority_tier), 6),
    )


@io_point("retrieval", "persist_evidence")
def persist_evidence(
    evidence_repo: EvidenceRepository,
    *,
    evidence: EvidenceModel,
    tenant_id: str,
) -> str:
    """将 Evidence 写入 evidence 表（session 提交由外层 session_scope 负责）。

    返回 evidence 行主键 id。
    """
    row = EvidenceRow(
        tenant_id=tenant_id,
        document_id=evidence.document_id,
        chunk_id=evidence.chunk_id,
        provider=evidence.source.provider,
        relevance_score=evidence.relevance_score,
        authority_score=evidence.authority_score,
        retrieved_at=evidence.source.retrieved_at,
        evidence_json=evidence.model_dump(mode="json"),
    )
    evidence_repo.add(row)
    logger.info(
        "evidence_persisted",
        extra={"extra": {"evidence_id": row.id, "document_id": evidence.document_id}},
    )
    return str(row.id)


__all__ = ["build_evidence", "persist_evidence"]