"""ADR-0011 新闻情绪打分单测。

覆盖关键词打分（利好/利空/中性/混合）、诚实标注（method/calibrated/低置信），
以及 analyze_news 对 NewsItem 列表的映射。
"""
from __future__ import annotations

from datetime import datetime

from finsage.providers.finance.domain import NewsItem
from finsage.sentiment import NewsSentiment, SentimentScore, analyze_news, score_sentiment


def test_positive_text():
    s = score_sentiment("公司业绩增长，盈利超预期")
    assert isinstance(s, SentimentScore)
    assert s.label == "positive"
    assert s.score > 0
    assert "增长" in s.matched_terms


def test_negative_text():
    s = score_sentiment("公司亏损，股价下跌")
    assert s.label == "negative"
    assert s.score < 0
    assert "亏损" in s.matched_terms


def test_neutral_text_no_keywords():
    s = score_sentiment("公司发布年度公告")
    assert s.label == "neutral"
    assert s.score == 0.0
    assert s.matched_terms == []


def test_mixed_text_balanced_neutral():
    s = score_sentiment("公司增长但面临风险")
    assert s.label == "neutral"
    assert s.score == 0.0


def test_honest_calibration_contract():
    s = score_sentiment("公司业绩增长")
    assert s.method == "keyword_rule_based"
    assert s.calibrated is False  # 待实测校准
    assert s.confidence == 0.5  # 固定低置信，不冒充高置信


def test_empty_text_neutral():
    s = score_sentiment("")
    assert s.label == "neutral"
    assert s.score == 0.0


def test_english_keywords():
    s = score_sentiment("company reports strong profit growth")
    assert s.label == "positive"
    assert s.score > 0


def _news(title: str, summary: str | None = None) -> NewsItem:
    return NewsItem(
        symbol="300750",
        market="CN",
        title=title,
        summary=summary,
        source="fake",
        retrieved_at=datetime.now(),
    )


def test_analyze_news_maps_items():
    items = [_news("公司业绩增长"), _news("公司亏损")]
    out = analyze_news(items)
    assert len(out) == 2
    assert all(isinstance(n, NewsSentiment) for n in out)
    assert out[0].sentiment.label == "positive"
    assert out[1].sentiment.label == "negative"
    assert out[0].title == "公司业绩增长"
    assert out[0].source == "fake"


def test_analyze_news_uses_summary():
    # 标题中性，摘要含利空关键词 -> 整体判负。
    items = [_news("公司公告", summary="公司面临重大诉讼风险")]
    out = analyze_news(items)
    assert out[0].sentiment.label == "negative"


def test_analyze_news_empty():
    assert analyze_news([]) == []
