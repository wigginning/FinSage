"""Search MCP Server（T403 + T404i，§14）。

Server：``finsage-search-mcp``。工具与规格 §14 冻结一致，共 3 个：
search_web / search_company / search_news。

依赖：``search_server.provider`` 的免费多引擎回退实现。三个工具均只消费
public provider 层函数；外部 Web 内容为不可信输入，见 provider 层安全约束（§14）。
"""
from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from finsage.observability.logger import get_logger

from .provider import SearchHit, SearchHitList, search_company, search_news, search_web

logger = get_logger(__name__)

# Server 名与规格 §14 冻结一致。
SERVER_NAME = "finsage-search-mcp"


def _as_hits(payload: SearchHitList) -> dict:
    return {
        "engine": payload.engine,
        "hits": [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in payload.hits],
    }


class SearchMCPServer:
    """封装 FastMCP 并暴露三个搜索工具。"""

    def __init__(self) -> None:
        self.app = FastMCP(SERVER_NAME)
        self._register()

    def _register(self) -> None:
        async def search_web_tool(query: str, limit: int = 10) -> dict:
            return _as_hits(search_web(query, limit=limit))

        async def search_company_tool(query: str, limit: int = 10) -> dict:
            return _as_hits(search_company(query, limit=limit))

        async def search_news_tool(query: str, limit: int = 10) -> dict:
            return _as_hits(search_news(query, limit=limit))

        self.app.add_tool(search_web_tool, name="search_web", description="通用网页搜索（§14）")
        self.app.add_tool(
            search_company_tool, name="search_company", description="公司信息搜索（§14）"
        )
        self.app.add_tool(search_news_tool, name="search_news", description="新闻搜索（§14）")

    async def list_tools(self) -> list[str]:
        """列出已注册工具名。"""
        tools = await self.app.list_tools()
        return [t.name for t in tools]

    def serve(self, *, transport: Literal["stdio", "sse", "streamable-http"] = "stdio") -> None:
        """启动 MCP server 进程（ADR-0021：作为外部工具面独立对外）。

        ``transport``：``stdio``（默认）/ ``sse`` / ``streamable-http``。
        """
        self.app.run(transport=transport)


__all__ = ["SearchMCPServer", "SERVER_NAME", "SearchHit"]