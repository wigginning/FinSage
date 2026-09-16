"""m04 MCP integration tests（T405 —— schema 与调用链联测，§12/13/14）。

覆盖：
1. 三个 MCP Server 的工具 schema（list_tools）与规格 §12/13/14 冻结一致；
2. Financial 工具只经 Provider Registry（注入伪 Provider，验证调用链 + 三大报表按 metric 过滤）；
3. Knowledge 工具检索接线（注入伪 embedder/hybrid_search/reranker/manager）；
4. Search 工具免费多引擎回退（mock requests 出站）。

不依赖真实网络 / Milvus / 模型，全部替换为测试替身。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from finsage.mcp import (
    build_financial_server,
    build_knowledge_server,
    build_search_server,
)
from finsage.providers.finance import ProviderRegistry
from finsage.providers.finance.domain import CompanyProfile, FinancialMetric, NewsItem, Quote

# ---- 伪 Provider（仅实现 FinancialDataProvider 契约）----


class _FakeProvider:
    name = "fake"

    def __init__(self, quotes=None, financials=None, profiles=None, news=None):
        self.quotes = quotes or []
        self.financials = financials or []
        self.profiles = profiles or []
        self.news = news or []
        self.calls = []

    async def get_quote(self, symbol, market):
        self.calls.append(("quote", symbol, market))
        if not self.quotes:
            raise RuntimeError("no fake quote")
        return self.quotes[0]

    async def get_financials(self, symbol, market, period):
        self.calls.append(("financials", symbol, market, period))
        return self.financials

    async def get_company_profile(self, symbol, market):
        self.calls.append(("profile", symbol, market))
        return self.profiles[0]

    async def get_news(self, symbol, market, limit=20):
        self.calls.append(("news", symbol, market, limit))
        return self.news


def _metric(metric: str, value: str = "100") -> FinancialMetric:
    return FinancialMetric(
        company="X",
        ticker="600519",
        market="CN",
        metric=metric,
        value=Decimal(value),
        currency="CNY",
        unit="CNY",
        period="FY2024",
        period_type="FY",
        source="fake",
        retrieved_at=datetime.now(UTC),
    )


def _quote() -> Quote:
    return Quote(
        symbol="600519", market="CN", name="X", price=Decimal("1500"), currency="CNY",
        timestamp=datetime.now(UTC), source="fake",
    )


def _profile() -> CompanyProfile:
    return CompanyProfile(symbol="600519", market="CN", name="X", source="fake",
                          retrieved_at=datetime.now(UTC))


def _news() -> NewsItem:
    return NewsItem(symbol="600519", market="CN", title="n1", source="fake",
                    retrieved_at=datetime.now(UTC))


def _registry(fake: _FakeProvider) -> ProviderRegistry:
    r = ProviderRegistry()
    r.register(
        fake,
        {
            "quote": ["CN"],
            "financials": ["CN"],
            "company_profile": ["CN"],
            "news": ["CN"],
        },
    )
    return r


async def _call(app, name: str, arguments: dict):
    """调用 FastMCP 工具并解包为结构化结果（供断言）。

    FastMCP ``call_tool(convert_result=True)`` 对无结构化输出的工具返回
    ``Sequence[TextContent]``（首个 content 为 JSON 文本）；有结构化输出时返回
    ``(unstructured_content, structured_content)`` 元组。统一提取结构化 dict。
    """
    result = await app.call_tool(name, arguments)
    if isinstance(result, tuple):
        return result[1]
    text = result[0].text if result else "{}"
    return json.loads(text)


# ---- 1. Tool schema ----

FINANCIAL_TOOLS = {
    "get_stock_quote", "get_financial_statements", "get_income_statement",
    "get_balance_sheet", "get_cash_flow", "get_company_profile", "get_news",
}
KNOWLEDGE_TOOLS = {"search_documents", "retrieve_evidence", "get_document", "get_document_page"}
SEARCH_TOOLS = {"search_web", "search_company", "search_news"}


async def test_financial_schema_matches_spec():
    srv = build_financial_server(registry=_registry(_FakeProvider()))
    assert set(await srv.list_tools()) == FINANCIAL_TOOLS


async def test_knowledge_schema_matches_spec():
    srv = build_knowledge_server(
        manager=_FakeManager(), embedder=_FakeEmbedder(), reranker=_FakeReranker()
    )
    assert set(await srv.list_tools()) == KNOWLEDGE_TOOLS


async def test_search_schema_matches_spec():
    srv = build_search_server()
    assert set(await srv.list_tools()) == SEARCH_TOOLS


# ---- 2. Financial 调用链（只经 Registry）----

async def test_get_stock_quote_via_registry():
    fake = _FakeProvider(quotes=[_quote()])
    srv = build_financial_server(registry=_registry(fake))
    out = await _call(srv.app, "get_stock_quote", {"symbol": "600519", "market": "CN"})
    assert fake.calls == [("quote", "600519", "CN")]
    assert out["symbol"] == "600519" and out["price"] == "1500"


async def test_get_invalid_tool_rejected():
    srv = build_financial_server(registry=_registry(_FakeProvider()))
    with pytest.raises(ToolError):
        await srv.app.call_tool("get_nonexistent_tool", {})


async def test_income_statement_filters_income_metrics():
    fake = _FakeProvider(
        financials=[
            _metric("revenue", "200"),
            _metric("net_income", "50"),
            _metric("total_assets", "900"),  # 应被过滤掉
        ]
    )
    srv = build_financial_server(registry=_registry(fake))
    out = await _call(
        srv.app, "get_income_statement", {"symbol": "x", "market": "CN", "period": "2024"}
    )
    metrics = [m["metric"] for m in out["items"]]
    assert metrics == ["revenue", "net_income"]


async def test_balance_sheet_filters_balance_metrics():
    fake = _FakeProvider(financials=[_metric("total_assets"), _metric("revenue")])
    srv = build_financial_server(registry=_registry(fake))
    out = await _call(
        srv.app, "get_balance_sheet", {"symbol": "x", "market": "CN", "period": "2024"}
    )
    assert [m["metric"] for m in out["items"]] == ["total_assets"]


async def test_cash_flow_filters_cashflow_metrics():
    fake = _FakeProvider(financials=[_metric("operating_cash_flow"), _metric("revenue")])
    srv = build_financial_server(registry=_registry(fake))
    out = await _call(srv.app, "get_cash_flow", {"symbol": "x", "market": "CN", "period": "2024"})
    assert [m["metric"] for m in out["items"]] == ["operating_cash_flow"]


async def test_get_company_profile_and_news():
    fake = _FakeProvider(profiles=[_profile()], news=[_news()])
    srv = build_financial_server(registry=_registry(fake))
    out = await _call(srv.app, "get_company_profile", {"symbol": "x", "market": "CN"})
    assert out["name"] == "X"
    out2 = await _call(srv.app, "get_news", {"symbol": "x", "market": "CN", "limit": 5})
    assert out2["items"] and out2["items"][0]["title"] == "n1"


# ---- 3. Knowledge 检索接线（伪依赖）----

class _FakeEmbedder:
    def encode_text(self, query):
        return ([0.1] * 4, {1: 0.5})


class _FakeReranker:
    def __init__(self, rerank_k=10):
        self.rerank_k = rerank_k

    def rerank(self, query, candidates):
        # 保持输入顺序，追加 rerank_score。
        ranked = [dict(c, rerank_score=0.9 - i * 0.1) for i, c in enumerate(candidates)]
        return ranked[: self.rerank_k]


class _FakeManager:
    def __init__(self):
        self.rows = []

    @property
    def client(self):
        return self

    def query(self, collection_name="", filter="", output_fields=None):
        return self.rows

    def search(self, *a, **k):
        return []

    def has_collection(self, name):
        return True


def _patch_retrieval(monkeypatch, hits):
    """把 hybrid_search 替换为返回固定 SearchResult 的实现。"""
    from finsage.retrieval import models as rm

    result = rm.SearchResult(
        query="q",
        hits=hits,
        dense_count=len(hits),
        sparse_count=len(hits),
    )
    monkeypatch.setattr("finsage.mcp.knowledge_server.hybrid_search", lambda *a, **k: result)


def _hit(pk="doc_0", text="t", page=1, section="s", tier=3):
    from finsage.retrieval.models import ChunkHit

    return ChunkHit(
        pk=pk, document_id="doc", chunk_id=pk, text=text, page=page,
        section=section, authority_tier=tier, dense_score=0.8,
    )


async def test_search_documents_returns_ranked_hits(monkeypatch):
    _patch_retrieval(monkeypatch, [_hit("doc_0"), _hit("doc_1")])
    srv = build_knowledge_server(
        manager=_FakeManager(), embedder=_FakeEmbedder(), reranker=_FakeReranker()
    )
    out = await _call(srv.app, "search_documents", {"query": "q"})
    assert out["query"] == "q"
    assert len(out["hits"]) == 2
    assert out["hits"][0]["rerank_score"] > out["hits"][1]["rerank_score"]


async def test_retrieve_evidence_produces_citation(monkeypatch):
    _patch_retrieval(monkeypatch, [_hit("doc_0", tier=5)])
    srv = build_knowledge_server(
        manager=_FakeManager(), embedder=_FakeEmbedder(), reranker=_FakeReranker()
    )
    out = await _call(srv.app, "retrieve_evidence", {"query": "q"})
    assert out["evidence"]
    ev = out["evidence"][0]
    assert ev["document_id"] == "doc" and ev["chunk_id"] == "doc_0"
    assert ev["source"]["authority_tier"] == 5 and ev["relevance_score"] > 0


async def test_retrieve_evidence_no_hits_raises(monkeypatch):
    _patch_retrieval(monkeypatch, [])
    srv = build_knowledge_server(
        manager=_FakeManager(), embedder=_FakeEmbedder(), reranker=_FakeReranker()
    )
    with pytest.raises(ToolError, match="FIN-3003"):
        await srv.app.call_tool("retrieve_evidence", {"query": "q"})


async def test_get_document_assembles_chunks():
    mgr = _FakeManager()
    mgr.rows = [{"chunk_id": "doc_1", "text": "b", "page": 2},
                {"chunk_id": "doc_0", "text": "a", "page": 1}]
    srv = build_knowledge_server(manager=mgr, embedder=_FakeEmbedder(), reranker=_FakeReranker())
    out = await _call(srv.app, "get_document", {"document_id": "doc"})
    assert out["pages"] == [1, 2]
    assert out["content"] == "a\n\nb"


async def test_get_document_page_filters_page():
    mgr = _FakeManager()
    mgr.rows = [{"chunk_id": "doc_1", "text": "b", "page": 2},
                {"chunk_id": "doc_0", "text": "a", "page": 1}]
    srv = build_knowledge_server(manager=mgr, embedder=_FakeEmbedder(), reranker=_FakeReranker())
    out = await _call(srv.app, "get_document_page", {"document_id": "doc", "page": 2})
    assert out["content"] == "b"


async def test_get_document_missing_raises():
    srv = build_knowledge_server(
        manager=_FakeManager(), embedder=_FakeEmbedder(), reranker=_FakeReranker()
    )
    with pytest.raises(ToolError):
        await srv.app.call_tool("get_document", {"document_id": "missing"})


# ---- 4. Search：免费多引擎回退 ----

def _html_bing():
    return ('<ol id="b_results"><li class="b_algo"><h2><a href="https://example.com">A</a></h2>'
            '<p>desc</p></li></ol>')


def _html_ddg():
    return ('<div class="result results_links"><a href="https://example.org">B</a>'
            '<a class="result__snippet">snip</a></div>')


def _mock_requests(monkeypatch, responses):
    import requests as req

    class _Resp:
        status_code = 200
        text = ""

    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(("get", url))
        r = _Resp()
        r.text = responses.get(("get", url), "")
        return r

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append(("post", url))
        r = _Resp()
        r.text = responses.get(("post", url), "")
        return r

    monkeypatch.setattr(req, "get", fake_get)
    monkeypatch.setattr(req, "post", fake_post)
    return calls


async def test_search_web_uses_bing_first(monkeypatch):
    calls = _mock_requests(monkeypatch, {("get", "https://www.bing.com/search"): _html_bing()})
    srv = build_search_server()
    out = await _call(srv.app, "search_web", {"query": "q"})
    assert out["engine"] == "bing"
    assert out["hits"][0]["title"] == "A"
    assert calls[0] == ("get", "https://www.bing.com/search")


async def test_search_web_falls_back_to_duckduckgo(monkeypatch):
    # Bing 返回空命中 -> fallback 到 DDG。
    _mock_requests(monkeypatch, {
        ("get", "https://www.bing.com/search"): "<html></html>",
        ("post", "https://html.duckduckgo.com/html/"): _html_ddg(),
    })
    srv = build_search_server()
    out = await _call(srv.app, "search_web", {"query": "q"})
    assert out["engine"] == "duckduckgo"
    assert out["hits"][0]["title"] == "B"


async def test_search_company_and_news_compose_query(monkeypatch):
    _mock_requests(monkeypatch, {("get", "https://www.bing.com/search"): _html_bing()})
    srv = build_search_server()
    out = await _call(srv.app, "search_company", {"query": "Apple"})
    assert out["hits"]
    out2 = await _call(srv.app, "search_news", {"query": "Tesla"})
    assert out2["hits"]


async def test_search_web_all_engines_fail_raises(monkeypatch):
    _mock_requests(monkeypatch, {
        ("get", "https://www.bing.com/search"): "<html></html>",
        ("post", "https://html.duckduckgo.com/html/"): "<html></html>",
    })
    srv = build_search_server()
    with pytest.raises(ToolError, match="FIN-2004"):
        await srv.app.call_tool("search_web", {"query": "q"})