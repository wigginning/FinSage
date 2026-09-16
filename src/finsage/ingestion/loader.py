"""文档加载入口（T203）。对接上层上传链路（m08 约定）与本地文件。

解析 PDF → 生成 ParsedDocument；解析失败抛 DocumentError（FIN-1101）。
"""

from __future__ import annotations

from pathlib import Path

from finsage.exceptions import DocumentError

from .models import ParsedDocument
from .pdf_parser import parse_pdf, parse_pdf_file


def load_document(
    source: bytes | str | Path,
    *,
    title: str = "",
    source_type: str = "upload",
) -> ParsedDocument:
    """按输入类型加载文档。

    - bytes：直接作为 PDF 字节流解析；
    - str/Path：作为本地文件路径读取后解析。
    其它类型一律抛 DocumentError，不做隐式猜测。
    """
    if isinstance(source, bytes):
        return parse_pdf(source, title=title, source_type=source_type)
    if isinstance(source, (str, Path)):
        return parse_pdf_file(source, source_type=source_type)
    raise DocumentError(f"unsupported document source type: {type(source).__name__}")


__all__ = ["load_document"]