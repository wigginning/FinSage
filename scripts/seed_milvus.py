"""Milvus 语料灌库脚本（让检索真正可产出）。

复用既有 ingestion 流水线（不重造）：
    load_document -> chunk_document -> extract_metadata -> BGE3Embedder.encode_chunks
    -> ensure_collection + index_chunks

幂等：index_chunks 的 pk 由 document_id+chunk_index 稳定合成，重复跑覆盖同文档分块。

用法（在项目根目录执行）：
    # 灌单个 PDF
    python scripts/seed_milvus.py --source data/sample.pdf \
        --company "示例公司" --ticker 000001 --market A

    # 灌整个目录（递归 *.pdf）
    python scripts/seed_milvus.py --source data/corpus/ --document-type report

    # 重建集合后灌库
    python scripts/seed_milvus.py --source data/corpus/ --force-recreate

    # 干跑：仅解析+分块，不连 Milvus、不加载模型、不写向量
    python scripts/seed_milvus.py --source data/ --dry-run

前置：
    - docker compose up -d 起 Milvus（见 docker-compose.yml，宿主端口 19730）；
    - FIN_MILVUS_HOST / FIN_MILVUS_PORT 指向可达实例（默认 localhost:19730）；
    - BGE-M3 模型：本地 model_local_dir 预下载，或首次运行联网缓存到 model_cache_dir。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

# 自包含：把 src 加入 path，使其可从项目根运行
# （与 scripts/probe_stack.py 顶层 import finsage 一致）。
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from finsage.ingestion import (  # noqa: E402
    BGE3Embedder,
    chunk_document,
    extract_metadata,
    index_chunks,
    load_document,
)
from finsage.retrieval.client import MilvusClientManager  # noqa: E402
from finsage.retrieval.schema import ensure_collection  # noqa: E402

# 单租户/无租户场景占位（与既有仓储缺省一致）。
_DEFAULT_TENANT = "__default__"


def _gather_pdfs(source: Path) -> list[Path]:
    """收集待灌文件：单文件直接返回；目录递归收集 *.pdf。"""
    if source.is_file():
        if source.suffix.lower() != ".pdf":
            raise SystemExit(f"仅支持 PDF：{source}")
        return [source]
    if source.is_dir():
        files = sorted(p for p in source.rglob("*.pdf") if p.is_file())
        if not files:
            raise SystemExit(f"目录内无 PDF：{source}")
        return files
    raise SystemExit(f"源不存在：{source}")


def ingest_document(
    manager: MilvusClientManager,
    embedder: BGE3Embedder,
    source: Path,
    *,
    tenant: str,
    meta: dict,
    dry_run: bool = False,
) -> int:
    """把单个文档灌入 Milvus，返回写入分块数（dry_run 返回分块数，不写）。"""
    parsed = load_document(str(source), title=source.stem, source_type="upload")
    document_id = uuid4().hex
    chunks = chunk_document(parsed, document_id)
    if not chunks:
        print(f"  [skip] {source.name}: 无有效分块")
        return 0

    # extract_metadata 不含 tenant_id，indexer 标量字段需要，显式注入。
    doc_meta = {**extract_metadata(title=source.stem, **meta), "tenant_id": tenant}

    if dry_run:
        print(f"  [dry] {source.name}: {len(chunks)} 分块（未连 Milvus / 未加载模型）")
        return len(chunks)

    indexed = embedder.encode_chunks(chunks)
    count = index_chunks(manager, indexed, doc_meta=doc_meta)
    print(f"  [ok]  {source.name}: 写入 {count}/{len(chunks)} 分块")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinSage Milvus 语料灌库")
    parser.add_argument("--source", required=True, help="PDF 文件或目录（递归 *.pdf）")
    parser.add_argument("--tenant", default=_DEFAULT_TENANT, help="租户 ID（默认 __default__）")
    parser.add_argument("--company", default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--market", default=None, help="如 A / HK / US")
    parser.add_argument("--document-type", dest="document_type", default=None)
    parser.add_argument("--report-period", dest="report_period", default=None)
    parser.add_argument("--authority-tier", dest="authority_tier", type=int, default=1)
    parser.add_argument(
        "--force-recreate", action="store_true", help="先删后建 finsage_chunks 集合"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅解析+分块，不连 Milvus、不加载模型、不写向量",
    )
    args = parser.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    files = _gather_pdfs(source)

    meta = {
        "company": args.company,
        "ticker": args.ticker,
        "market": args.market,
        "document_type": args.document_type,
        "report_period": args.report_period,
        "authority_tier": args.authority_tier,
        "published_at": None,
    }

    print(f"待灌文件：{len(files)} 个（来源 {source}）")
    if args.dry_run:
        manager = None  # type: ignore[assignment]
        embedder = None  # type: ignore[assignment]
    else:
        manager = MilvusClientManager()
        embedder = BGE3Embedder()
        ensure_collection(manager, force_recreate=args.force_recreate)

    total = 0
    try:
        for f in files:
            total += ingest_document(
                manager, embedder, f, tenant=args.tenant, meta=meta, dry_run=args.dry_run
            )
    finally:
        if manager is not None:
            manager.close()

    print(f"完成：共写入 {total} 个分块" if not args.dry_run else f"干跑完成：共 {total} 个分块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
