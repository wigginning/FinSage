"""文档分块（T205）。将 ParsedDocument 的页面文本切成 Chunk 序列。

规则：
- 按「目标字符数 + 重叠」滑动切分，CJK 与拉丁文本统一按字符计；
- 分块记录所属页码（页内首个字符所在页）与章节（取该页 section）；
- 空页不产出块；同一页文本超过目标长度才跨块；
- 分块以 document_id 为根，chunk_index 从 0 递增。
"""

from __future__ import annotations

import hashlib

from finsage.observability.logger import io_point

from .models import Chunk, ParsedDocument

# 目标分块字符数与相邻重叠（可调，转入 Evaluation）。
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """把单段文本按 size/overlap 切成片段序列。"""
    segments: list[str] = []
    i = 0
    n = len(text)
    step = max(1, size - overlap)
    while i < n:
        segments.append(text[i : i + size])
        i += step
    return segments


@io_point("ingestion", "chunk")
def chunk_document(
    doc: ParsedDocument,
    document_id: str,
    *,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """把解析文档切分为分块序列（逐页处理，区段内滑动重叠）。"""
    if size <= overlap:
        raise ValueError("chunk size must be greater than overlap")

    chunks: list[Chunk] = []
    for page in doc.pages:
        text = page.text.strip()
        if not text:
            continue
        for seg in _split_text(text, size, overlap):
            seg = seg.strip()
            if not seg:
                continue
            chunks.append(
                Chunk(
                    document_id=document_id,
                    chunk_index=len(chunks),
                    text=seg,
                    page=page.number,
                    section=page.section,
                    text_hash=_hash(seg),
                    text_length=len(seg),
                )
            )
    return chunks