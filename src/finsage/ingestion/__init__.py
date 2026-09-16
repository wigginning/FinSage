"""ingestion 域：文档解析、分块、元数据、嵌入、Milvus 索引写入。"""

from .chunker import CHUNK_OVERLAP, CHUNK_SIZE, chunk_document
from .embedding import BGE3Embedder
from .indexer import index_chunks
from .loader import load_document
from .metadata import extract_metadata
from .models import Chunk, IndexedChunk, Page, ParsedDocument
from .pdf_parser import parse_pdf

__all__ = [
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "chunk_document",
    "BGE3Embedder",
    "index_chunks",
    "load_document",
    "extract_metadata",
    "Chunk",
    "IndexedChunk",
    "Page",
    "ParsedDocument",
    "parse_pdf",
]