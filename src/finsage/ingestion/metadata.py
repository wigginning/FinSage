"""元数据提取（T206）。将显式来源字段映射为 §6 Milvus 字段 + 引用映射字段。

说明：financial 实体的自动识别（NER）不在本模块职责内；company/ticker/market 等
均由上层（上传链路/标定）显式传入，本函数仅做类型规范化与确定性映射，杜绝凭空猜测。
report_period 支持从标题做保守正则探测（可选），默认以传入值为准。
"""

from __future__ import annotations

import re
from datetime import datetime

from finsage.observability.logger import io_point

# §6.2 集合字段（用于校验/记录，避免漏字段）。
COLLECTION_FIELDS = (
    "pk",
    "document_id",
    "chunk_id",
    "text",
    "dense_vector",
    "sparse_vector",
    "tenant_id",
    "company",
    "ticker",
    "market",
    "document_type",
    "report_period",
    "published_at_ts",
    "page",
    "authority_tier",
)

# 报告期保守探测：YYYY 或 YYYYQ1 或 YYYY年Q1。
_REPORT_PERIOD = re.compile(r"(20\d{2})(?:\s*年|[Qq]([1-4]))")


def _iso_to_ts(value: datetime | None) -> int | None:
    """流转为 epoch 秒（INT64，§6.2 published_at_ts）。"""
    if value is None:
        return None
    return int(value.timestamp())


def _probe_report_period(title: str | None) -> str | None:
    """从标题保守提取报告期；未命中返回 None（不做强推断）。"""
    if not title:
        return None
    m = _REPORT_PERIOD.search(title)
    if not m:
        return None
    year = m.group(1)
    quarter = m.group(2)
    return f"{year}Q{quarter}" if quarter else year


@io_point("ingestion", "extract_metadata", mask_args=False)
def extract_metadata(
    *,
    title: str = "",
    company: str | None = None,
    ticker: str | None = None,
    market: str | None = None,
    document_type: str | None = None,
    report_period: str | None = None,
    published_at: datetime | None = None,
    authority_tier: int = 1,
    provider: str | None = None,
    url: str | None = None,
) -> dict:
    """按 §6 集合字段生成文档级元数据字典；值缺失的键取 None 占位。

    authority_tier 与 provider/url 同时用于后续 SourceRef 引用映射。
    """
    period = report_period or _probe_report_period(title) or None
    return {
        "company": company,
        "ticker": ticker,
        "market": market,
        "document_type": document_type,
        "report_period": period,
        "published_at_ts": _iso_to_ts(published_at),
        "authority_tier": int(authority_tier),
        # 引用映射附加字段（非 §6 vector 字段，但 Evidence/SourceRef 需要）。
        "provider": provider,
        "url": url,
        "title": title,
    }