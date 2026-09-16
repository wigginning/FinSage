"""PDF 解析（T204）。基于 PyMuPDF（fitz）。

规则：
- 逐页提取纯文本，保留页码（从 1 起）与章节标题（启发式行首匹配）；
- 解析失败抛 DocumentError（FIN-1101）；超过尺寸上限抛 DocumentTooLargeError（FIN-1102）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from finsage.exceptions import DocumentError, DocumentTooLargeError
from finsage.observability.logger import get_logger, io_point

from .models import Page, ParsedDocument

logger = get_logger(__name__)

# 允许的最大文档字节数（T204 尺寸校验，归入 FIN-1102 语义）。
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
# 允许解析的最大页数（防御性上限）。
MAX_PAGES = 10_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_section_heading(line: str) -> bool:
    """启发式：认为是章节标题的判定（用于 T205 section 记录，非强制）。"""
    combined = line.rstrip()
    if not combined:
        return False
    return len(combined) <= 60 and (
        combined[0].isdigit()
        or combined.startswith(("第一", "第二", "第三", "第四", "第五", "第六", "第七", "第八"))
        or combined[0] in "一二三四五六七八九"
        or combined.startswith("【")
    )


@io_point("ingestion", "pdf_parse")
def parse_pdf(data: bytes, *, title: str = "", source_type: str = "upload") -> ParsedDocument:
    """解析 PDF 字节流为 ParsedDocument。

    仅接受非空且不超过 MAX_DOCUMENT_BYTES 的输入；异常抛出而不吞。
    """
    if not data:
        raise DocumentError("PDF content is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError(f"PDF exceeds {MAX_DOCUMENT_BYTES} bytes")

    try:
        import fitz

        pdf = fitz.open(stream=data, filetype="pdf")  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - 各类损坏/加密统一归解析失败
        raise DocumentError(f"unable to open pdf: {type(exc).__name__}") from exc

    try:
        page_count = pdf.page_count
        if page_count == 0 or page_count > MAX_PAGES:
            raise DocumentError(f"invalid page count: {page_count}")

        pages: list[Page] = []
        for i, page in enumerate(pdf, start=1):
            text = page.get_text("text") or ""
            pages.append(Page(number=i, text=text))
    finally:
        pdf.close()

    for pg in pages:
        for line in pg.text.splitlines():
            if _is_section_heading(line):
                pg.section = line.strip()
                break

    doc = ParsedDocument(
        title=title or "untitled",
        source_type=source_type,
        pages=pages,
        metadata={"sha256": _sha256(data), "page_count": page_count},
    )
    logger.info("pdf_parsed", extra={"extra": {"title": doc.title, "pages": len(pages)}})
    return doc


def parse_pdf_file(path: str | Path, *, source_type: str = "upload") -> ParsedDocument:
    """从文件路径解析 PDF（测试/本地工具用）。"""
    return parse_pdf(Path(path).read_bytes(), title=Path(path).name, source_type=source_type)