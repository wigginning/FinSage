"""新闻情绪打分（ADR-0011 —— F1 扩展，规则法，待实测校准）。

确定性关键词打分：统计利好/利空关键词命中数，``score = (pos - neg) / (pos + neg)``
落在 ``[-1, 1]``。**不调用 LLM、不依赖训练模型**（AGENTS.md §3/§10）。

诚实标注：``method = "keyword_rule_based"``、``calibrated = False``（待实测校准）、
``confidence`` 固定低值（0.5）。情绪分数是确定性*信号*，不是高置信事实；未经
实测校准不得当作权威情绪结论对外呈现。关键词词表是首版近似，A 股金融文本上的
精确率/召回率未知，须实测后方可上调置信度。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from finsage.models.claims import SentimentSummary
from finsage.providers.finance.domain import NewsItem

__all__ = [
    "SentimentLabel",
    "SentimentScore",
    "NewsSentiment",
    "SentimentSummary",
    "score_sentiment",
    "summarize_sentiment",
    "analyze_news",
]

SentimentLabel = Literal["positive", "negative", "neutral"]

# 利好关键词（首版近似，待实测校准）。
_POSITIVE_TERMS: tuple[str, ...] = (
    "增长", "上涨", "盈利", "利好", "突破", "超预期", "提升", "改善", "回购",
    "增持", "中标", "签约", "创新高", "扭亏", "分红", "派息", "获批", "合作",
    "扩张", "强劲", "上升", "大涨", "涨停", "净利", "营收增长",
    "growth", "profit", "beat", "upgrade", "buyback", "surge", "rally",
    "record", "strong", "gain", "outperform",
)

# 利空关键词（首版近似，待实测校准）。
_NEGATIVE_TERMS: tuple[str, ...] = (
    "下跌", "亏损", "利空", "下滑", "减持", "违规", "处罚", "诉讼", "风险",
    "暴跌", "退市", "债务", "违约", "爆雷", "下调", "警示", "立案", "调查",
    "停产", "裁员", "下降", "大跌", "跌停", "净亏",
    "loss", "decline", "downgrade", "lawsuit", "risk", "drop", "plunge",
    "default", "weak", "miss", "underperform",
)

# 标签阈值：|score| 低于该值视为中性。
_LABEL_THRESHOLD = 0.2

# 规则法固定低置信（待实测校准，不冒充高置信）。
_RULE_CONFIDENCE = 0.5


class SentimentScore(BaseModel):
    """单条文本的情绪打分（ADR-0011）。"""

    score: float = Field(ge=-1, le=1, description="情绪分（-1 利空 .. 1 利好）")
    label: SentimentLabel
    confidence: float = Field(ge=0, le=1, description="置信度（规则法固定低值）")
    method: str = "keyword_rule_based"
    calibrated: bool = False  # 待实测校准
    matched_terms: list[str] = Field(default_factory=list, description="命中的关键词（可审计）")


class NewsSentiment(BaseModel):
    """新闻条目 + 情绪打分（ADR-0011）。"""

    title: str
    source: str
    published_at: datetime | None = None
    sentiment: SentimentScore


def _hits(text: str, terms: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [t for t in terms if t in low]


def score_sentiment(text: str) -> SentimentScore:
    """对文本做确定性关键词情绪打分。

    ``score = (pos - neg) / (pos + neg)``；无命中 → ``neutral`` / ``score = 0``。
    ``|score| < 0.2`` 视为中性。置信度固定 0.5（规则法，待实测校准）。
    """
    pos = _hits(text or "", _POSITIVE_TERMS)
    neg = _hits(text or "", _NEGATIVE_TERMS)
    total = len(pos) + len(neg)
    if total == 0:
        return SentimentScore(
            score=0.0,
            label="neutral",
            confidence=_RULE_CONFIDENCE,
            matched_terms=[],
        )
    score = (len(pos) - len(neg)) / total
    if score > _LABEL_THRESHOLD:
        label: SentimentLabel = "positive"
    elif score < -_LABEL_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"
    return SentimentScore(
        score=round(score, 4),
        label=label,
        confidence=_RULE_CONFIDENCE,
        matched_terms=pos + neg,
    )


def summarize_sentiment(texts: list[str]) -> SentimentSummary:
    """对一组文本（通常是检索到的证据文本）做情绪聚合（ADR-0018）。

    确定性聚合：逐条 ``score_sentiment`` 后统计三档条数与均值。空输入返回
    ``analyzed=0`` 的全零聚合（不伪造"中性"结论）。``calibrated`` 恒为
    ``False`` —— 规则法未校准，调用方必须在呈现层标注（AGENTS.md §10）。
    """
    if not texts:
        return SentimentSummary()

    scores = [score_sentiment(t) for t in texts]
    total = len(scores)
    return SentimentSummary(
        analyzed=total,
        positive=sum(1 for s in scores if s.label == "positive"),
        neutral=sum(1 for s in scores if s.label == "neutral"),
        negative=sum(1 for s in scores if s.label == "negative"),
        mean_score=round(sum(s.score for s in scores) / total, 4),
    )


def analyze_news(news_items: list[NewsItem]) -> list[NewsSentiment]:
    """对新闻列表逐条打分（标题 + 摘要拼接后打分）。"""
    results: list[NewsSentiment] = []
    for item in news_items:
        text = " ".join(
            part for part in (item.title, item.summary) if part
        )
        results.append(
            NewsSentiment(
                title=item.title,
                source=item.source,
                published_at=item.published_at,
                sentiment=score_sentiment(text),
            )
        )
    return results
