"""Search MCP 服务提供者层：免费多引擎回退（T403，§14）。

规格 §14 冻结了 search_web / search_company / search_news 三个工具名，未冻结后端。
m04 采用用户选定的「免费多引擎回退」方案：以纯 Python `requests` 接入免费搜索引擎
（Bing / DuckDuckGo），无需 API Key。各引擎独立实现，失败时按顺序 fallback。

安全约束（§14 / AGENTS.md §7）：
- 外部 Web 内容是不可信输入；本层只采集纯文本片段，绝不把页面内容当作可执行/系统指令；
- 返回结果仅含 title / url / snippet 结构化字段，供上层消费，不执行任何页面内脚本。

实现为确定性（不调用 LLM），纯凭 HTTP/HTML 文本处理（AGENTS.md §3）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from finsage.exceptions import ProviderBadResponseError, ProviderError, ProviderTimeoutError
from finsage.observability.logger import get_logger, io_point

logger = get_logger(__name__)

# 免费搜索引擎（无 API Key）出站域名，用于最小化请求目标。
_ENGINES = ("bing", "duckduckgo")

# 请求统一超时（工程默认，不伪装为数据源性能结论）。
_TIMEOUT = 10.0

_UA = "Mozilla/5.0 (compatible; FinSage/1.0)"


@dataclass
class SearchHit:
    """一条搜索结果（title / url / snippet）。"""

    title: str
    url: str
    snippet: str = ""


@dataclass
class SearchHitList:
    """一次搜索的产出：命中列表 + 命中使用的引擎。"""

    query: str
    hits: list[SearchHit] = field(default_factory=list)
    engine: str = ""


@io_point("mcp.search", "bing")
def _search_bing(query: str, limit: int = 10) -> list[SearchHit]:
    """Bing 网页搜索结果（HTML 解析）。失败抛 ProviderError。"""
    url = "https://www.bing.com/search"
    params = {"q": query, "count": str(limit)}
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    except requests.Timeout as exc:
        raise ProviderTimeoutError("bing search timed out") from exc
    except requests.RequestException as exc:
        raise ProviderBadResponseError(f"bing search failed: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise ProviderBadResponseError(f"bing returned {resp.status_code}")
    return _parse_bing(resp.text, limit)


def _parse_bing(html: str, limit: int) -> list[SearchHit]:
    """Bing 结果页解析：取 <li class="b_algo"> 中标题/链接/摘要。"""
    hits: list[SearchHit] = []
    for item in html.split('<li class="b_algo"')[1:]:
        title = _strip_tags(_first_tag(item, "<h2>", "</h2>"))
        url = _first_attr(item, "<a ", ' href="')
        snippet = _strip_tags(_first_tag(item, "<p>", "</p>"))
        if title and url and url.startswith("http"):
            hits.append(SearchHit(title=title, url=url, snippet=snippet))
        if len(hits) >= limit:
            break
    return hits


@io_point("mcp.search", "duckduckgo")
def _search_duckduckgo(query: str, limit: int = 10) -> list[SearchHit]:
    """DuckDuckGo HTML 结果。失败抛 ProviderError。"""
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = requests.post(
            url, data={"q": query}, headers={"User-Agent": _UA}, timeout=_TIMEOUT
        )
    except requests.Timeout as exc:
        raise ProviderTimeoutError("duckduckgo search timed out") from exc
    except requests.RequestException as exc:
        raise ProviderBadResponseError(f"duckduckgo search failed: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise ProviderBadResponseError(f"duckduckgo returned {resp.status_code}")
    return _parse_duckduckgo(resp.text, limit)


def _parse_duckduckgo(html: str, limit: int) -> list[SearchHit]:
    """DDG HTML 结果页解析：取 result__a / result__snippet。"""
    hits: list[SearchHit] = []
    for block in html.split('class="result results_links')[1:]:
        title = _inner_text(block, "<a ")
        url = _first_attr(block, '<a ', ' href="')
        snippet = _inner_text(block, 'class="result__snippet"')
        if title and url.startswith("http"):
            hits.append(SearchHit(title=title, url=url, snippet=snippet))
        if len(hits) >= limit:
            break
    return hits


def _inner_text(text: str, marker: str) -> str:
    """取 marker 之后第一个标签的 inner text（到 ``</a>`` 结束）。

    DDG 的标题/摘要均为 ``<a ...>文本</a>`` 结构；先定位 marker，再跳过其后的
    开标签（首个 ``>``），取下标签前的纯文本，避免把 ``href=...`` 等属性误当标题。
    """
    i = text.find(marker)
    if i < 0:
        return ""
    j = text.find(">", i + len(marker))
    if j < 0:
        return ""
    k = text.find("</a>", j + 1)
    if k < 0:
        return ""
    return _strip_tags(text[j + 1:k])


def _first_tag(text: str, start_marker: str, end_marker: str) -> str:
    """取 start_marker 之后到 end_marker 之前的子串；任一缺失返回空。"""
    i = text.find(start_marker)
    if i < 0:
        return ""
    rest = text[i + len(start_marker):]
    j = rest.find(end_marker)
    if j < 0:
        return ""
    return rest[:j]


def _first_attr(text: str, tag_marker: str, attr_prefix: str) -> str:
    """在 tag_marker 区间内取属性值。"""
    i = text.find(tag_marker)
    if i < 0:
        return ""
    rest = text[i:]
    j = rest.find(attr_prefix)
    if j < 0:
        return ""
    k = rest.find('"', j + len(attr_prefix))
    if k < 0:
        return ""
    return rest[j + len(attr_prefix):k]


def _strip_tags(html: str) -> str:
    import html as _html  # noqa: PLC0415 - 局部使用
    import re  # noqa: PLC0415 - 局部使用

    return _html.unescape(re.sub(r"<[^>]+>", "", html)).strip()


@io_point("mcp.search", "search_web")
def search_web(query: str, *, limit: int = 10) -> SearchHitList:
    """免费多引擎回退搜索：按 [bing, duckduckgo] 顺序，全部失败抛最终错误。"""
    last_error: ProviderError | None = None
    for engine in _ENGINES:
        try:
            hits = (
                _search_bing(query, limit)
                if engine == "bing"
                else _search_duckduckgo(query, limit)
            )
            if hits:
                return SearchHitList(query=query, hits=hits, engine=engine)
            last_error = ProviderBadResponseError(f"{engine} returned empty results")
        except ProviderError as exc:
            logger.warning(
                "search_engine_failed", extra={"extra": {"engine": engine, "error": str(exc)}}
            )
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ProviderBadResponseError("no free search engine available")


def search_company(company: str, *, limit: int = 10) -> SearchHitList:
    """搜索公司信息（§14，search_company）。基于 search_web 的组合查询。"""
    q = f"{company} company profile"
    return search_web(q, limit=limit)


def search_news(query: str, *, limit: int = 10) -> SearchHitList:
    """搜索新闻（§14，search_news）。基于 search_web 的组合查询。"""
    q = f"{query} news"
    return search_web(q, limit=limit)


__all__ = [
    "SearchHit",
    "SearchHitList",
    "search_web",
    "search_company",
    "search_news",
    "_ENGINES",
]