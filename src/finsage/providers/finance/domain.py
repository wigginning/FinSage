"""Provider 域领域模型（m03，§4.6/4.7 + 工程补全）。

规格 §4 已冻结 Quote / FinancialMetric 完整字段；
ProviderHealth 对照 §5.18 provider_health 表落地；
CompanyProfile / NewsItem 规格仅列名（§9.1）未给字段 —— 本模块按常见金融数据
源惯例定义并标注【工程补全，待规格评审】（遵循 AGENTS.md §10 诚实标注，不伪装冻结）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# §4.6 FinancialMetric（FROZEN）
PeriodType = Literal["FY", "Q1", "Q2", "Q3", "Q4", "TTM", "YTD", "DATE"]


class FinancialMetric(BaseModel):
    """财务指标（§4.6）。"""

    company: str
    ticker: str
    market: str
    metric: str
    value: Decimal
    currency: str | None = None
    unit: str | None = None
    period: str
    period_type: PeriodType
    source: str
    source_timestamp: datetime | None = None
    retrieved_at: datetime


# §4.7 Quote（FROZEN）
class Quote(BaseModel):
    """行情报价（§4.7）。"""

    symbol: str
    market: str
    name: str | None = None
    price: Decimal
    currency: str
    timestamp: datetime
    source: str


# §5.18 ProviderHealth（对照 provider_health 表）
class ProviderHealth(BaseModel):
    """Provider 健康度（对照 §5.18 表）。"""

    provider_name: str
    capability: str
    status: Literal["healthy", "degraded", "down"]
    success_rate: Decimal = Field(decimal_places=6)
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_count: int = 0
    updated_at: datetime


class CompanyProfile(BaseModel):
    """公司概况。【工程补全，待规格评审】（规格 §9.1 仅列名）。"""

    symbol: str
    market: str
    name: str
    currency: str | None = None
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    website: str | None = None
    country: str | None = None
    exchange: str | None = None
    source: str
    retrieved_at: datetime


class NewsItem(BaseModel):
    """公司新闻条目。【工程补全，待规格评审】（规格 §9.1 仅列名）。"""

    symbol: str
    market: str
    title: str
    url: str | None = None
    published_at: datetime | None = None
    source: str
    summary: str | None = None
    retrieved_at: datetime


__all__ = [
    "FinancialMetric",
    "Quote",
    "ProviderHealth",
    "CompanyProfile",
    "NewsItem",
    "PeriodType",
]