"""Knowledge MCP Server（T402 + T404h，§13）。

Server：``finsage-knowledge-mcp``。工具集合与规格 §13 冻结一致，共 4 个：
search_documents / retrieve_evidence / get_document / get_document_page。

接入（依赖 m02 检索层，AGENTS.md §5 RAG 约束）：
- search_documents：BGE-M3 编码 query -> hybrid_search（dense+sparse）-> BGE-Reranker 重排；
- retrieve_evidence：在检索命中上产出 Evidence 对象（citation 可溯源）；
- get_document / get_document_page：按 document_id（及页码）从 Milvus 读出片段文本。

实现基于 FastMCP；依赖（embedder / manager / reranker）可注入以便替换。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from finsage.exceptions import NoEvidenceError, RetrievalError
from finsage.observability.logger import get_logger, io_point
from finsage.retrieval import (
    BGEReranker,
    ChunkHit,
    MilvusClientManager,
    build_evidence,
    hybrid_search,
)

logger = get_logger(__name__)

# Server 名与规格 §13 冻结一致。
SERVER_NAME = "finsage-knowledge-mcp"

# get_document/get_document_page 读取的 Milvus 字段。
_DOC_FIELDS = ["pk", "document_id", "chunk_id", "text", "page", "section", "authority_tier"]


class KnowledgeMCPServer:
    """封装 FastMCP 并注入检索依赖（embedder / manager / reranker）。"""

    def __init__(
        self,
        manager: MilvusClientManager | None = None,
        reranker: BGEReranker | None = None,
        embedder: Any | None = None,
        *,
        top_k: int = 10,
    ) -> None:
        self.manager = manager or MilvusClientManager()
        self.reranker = reranker or BGEReranker(rerank_k=top_k)
        self.embedder = embedder
        self.top_k = top_k
        self.app = FastMCP(SERVER_NAME)
        self._register()

    def _get_embedder(self):
        """返回 query 编码器（首次用到时构造 BGE3Embedder）。"""
        if self.embedder is None:
            from finsage.ingestion.embedding import BGE3Embedder  # noqa: PLC0415

            self.embedder = BGE3Embedder()
        return self.embedder

    def _register(self) -> None:
        top_k = self.top_k

        async def search_documents(
            query: str, tenant_id: str | None = None, limit: int = top_k
        ) -> dict:
            return await self._search_documents(query, tenant_id, limit)

        async def retrieve_evidence(
            query: str, tenant_id: str | None = None, limit: int = top_k
        ) -> dict:
            return await self._retrieve_evidence(query, tenant_id, limit)

        async def get_document(document_id: str) -> dict:
            return self._get_document(document_id)

        async def get_document_page(document_id: str, page: int) -> dict:
            return self._get_document_page(document_id, page)

        self.app.add_tool(
            search_documents, name="search_documents", description="语义检索文档片段（§13）"
        )
        self.app.add_tool(
            retrieve_evidence, name="retrieve_evidence", description="检索并产出可溯源证据（§13）"
        )
        self.app.add_tool(
            get_document, name="get_document", description="按 document_id 取文档内容（§13）"
        )
        self.app.add_tool(
            get_document_page,
            name="get_document_page",
            description="按 document_id + 页码取该页内容（§13）",
        )

    # ---- 检索实现 ----

    @io_point("mcp.knowledge", "search_documents")
    async def _search_documents(self, query: str, tenant_id: str | None, limit: int) -> dict:
        dense, sparse = self._get_embedder().encode_text(query)
        result = hybrid_search(
            self.manager,
            query=query,
            dense_vector=dense,
            sparse_vector=sparse,
            candidate_k=max(limit, 50),
            tenant_id=tenant_id,
        )
        ranked = self.reranker.rerank(query, [_hit_to_dict(h) for h in result.hits])
        return {"query": query, "hits": [dict(r) for r in ranked]}

    @io_point("mcp.knowledge", "retrieve_evidence")
    async def _retrieve_evidence(self, query: str, tenant_id: str | None, limit: int) -> dict:
        dense, sparse = self._get_embedder().encode_text(query)
        result = hybrid_search(
            self.manager,
            query=query,
            dense_vector=dense,
            sparse_vector=sparse,
            candidate_k=max(limit, 50),
            tenant_id=tenant_id,
        )
        if not result.hits:
            raise NoEvidenceError("no evidence found for query")
        ranked = self.reranker.rerank(query, [_hit_to_dict(h) for h in result.hits])[:limit]
        evidence = [
            build_evidence(hit=_dict_to_hit(r), source_meta=_source_meta(r)).model_dump(mode="json")
            for r in ranked
        ]
        return {"query": query, "evidence": evidence}

    # ---- 文档读取 ----

    @io_point("mcp.knowledge", "get_document")
    def _get_document(self, document_id: str) -> dict:
        """取文档全部片段文本（按 chunk 序号排序）。"""
        rows = self._query_by_document(document_id)
        if not rows:
            raise RetrievalError(f"document not found: {document_id}")
        chunks = sorted(rows, key=_chunk_index)
        return {
            "document_id": document_id,
            "pages": [r.get("page") for r in chunks],
            "content": "\n\n".join(r.get("text", "") for r in chunks),
        }

    @io_point("mcp.knowledge", "get_document_page")
    def _get_document_page(self, document_id: str, page: int) -> dict:
        rows = self._query_by_document(document_id)
        filtered = [r for r in rows if r.get("page") == page]
        if not filtered:
            raise RetrievalError(f"page not found: {document_id}#{page}")
        chunks = sorted(filtered, key=_chunk_index)
        return {
            "document_id": document_id,
            "page": page,
            "content": "\n\n".join(r.get("text", "") for r in chunks),
        }

    def _query_by_document(self, document_id: str) -> list[dict]:
        """从 Milvus 按 document_id 读出片段记录（标量）。"""
        from finsage.retrieval.schema import escape_expr_str

        resp = self.manager.client.query(
            collection_name="finsage_chunks",
            filter=f'document_id == "{escape_expr_str(document_id)}"',
            output_fields=_DOC_FIELDS,
        )
        return list(resp) if resp else []

    async def list_tools(self) -> list[str]:
        """列出已注册工具名。"""
        tools = await self.app.list_tools()
        return [t.name for t in tools]

    def serve(
        self, *, transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    ) -> None:
        """启动 MCP server 进程（ADR-0021：作为外部工具面独立对外）。

        ``transport``：``stdio``（默认）/ ``sse`` / ``streamable-http``。
        """
        self.app.run(transport=transport)


def _hit_to_dict(hit: ChunkHit) -> dict:
    """把 ChunkHit 转成 reranker 需要的 dict（须含 id/text）。"""
    return {
        "id": hit.pk,
        "text": hit.text,
        "document_id": hit.document_id,
        "chunk_id": hit.chunk_id,
        "page": hit.page,
        "section": hit.section,
        "authority_tier": hit.authority_tier,
    }


def _dict_to_hit(data: dict) -> ChunkHit:
    """把重排后的 dict 转回 ChunkHit（供 build_evidence）。"""
    return ChunkHit(
        pk=data["id"],
        document_id=data.get("document_id", ""),
        chunk_id=data.get("chunk_id", ""),
        text=data.get("text", ""),
        page=data.get("page"),
        section=data.get("section"),
        authority_tier=int(data.get("authority_tier") or 1),
        rerank_score=float(data["rerank_score"]) if data.get("rerank_score") is not None else None,
    )


def _source_meta(hit: dict) -> dict:
    return {
        "provider": "milvus",
        "url": None,
        "title": hit.get("document_id"),
        "published_at": datetime.now(UTC),
        "authority_tier": hit.get("authority_tier", 1),
    }


def _chunk_index(row: dict) -> int:
    """chunk_id 形如 {document_id}_{index}，取序号用于排序。"""
    try:
        return int(str(row.get("chunk_id", "0")).rsplit("_", 1)[-1])
    except ValueError:
        return 0


__all__ = [
    "KnowledgeMCPServer",
    "SERVER_NAME",
    "build_evidence",
    "hybrid_search",
    "ChunkHit",
]