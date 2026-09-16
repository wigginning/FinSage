"""RAG 域仓储：documents、document_chunks（规格 §5.8–5.9）。"""

from __future__ import annotations

from finsage.persistence.models.rag import Document, DocumentChunk
from finsage.persistence.repositories.base import FilteredRepository, TenantScopedRepository


class DocumentRepository(TenantScopedRepository):
    """文档仓储：注入租户后自动限该租户；白名单筛选：sha256 / company / ticker / status。"""

    model = Document
    allow_filters = frozenset({"sha256", "company", "ticker", "document_type", "status"})

    def find_by_sha256(self, sha256: str):
        """按内容哈希取文档（域对象或 None）。"""
        return self.find_one(sha256=sha256)

    def list_by_ticker(self, ticker: str, *, limit: int = 100, offset: int = 0) -> list:
        """按证券代码取文档（域对象列表）。"""
        return self.find_many(ticker=ticker, limit=limit, offset=offset)


class DocumentChunkRepository(FilteredRepository):
    """文档片段仓储。白名单筛选：document_id / milvus_pk（预留）。"""

    model = DocumentChunk
    allow_filters = frozenset({"document_id", "milvus_pk"})

    def list_for_document(self, document_id: str, *, limit: int = 500, offset: int = 0) -> list:
        """按文档取片段，按序号升序（域对象列表）。"""
        stmt = (
            self.filter(document_id=document_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.execute(stmt).scalars().all())


__all__ = ["DocumentRepository", "DocumentChunkRepository"]
