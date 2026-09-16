"""MCP 服务层（m04，§12/13/14）。

暴露三个 MCP Server 的装配工厂：
- ``build_financial_server`` -> FinancialMCPServer（§12，经 Provider Registry）；
- ``build_knowledge_server`` -> KnowledgeMCPServer（§13，对接 m02 检索）；
- ``build_search_server`` -> SearchMCPServer（§14，免费多引擎回退）。

Server 名（MCP server id）与规格冻结一致：finsage-financial-mcp /
finsage-knowledge-mcp / finsage-search-mcp。
"""
from __future__ import annotations

from finsage.providers.finance import ProviderRegistry

from .financial_server import FinancialMCPServer
from .knowledge_server import KnowledgeMCPServer
from .search_server import SearchMCPServer


def build_financial_server(
    registry: ProviderRegistry | None = None,
) -> FinancialMCPServer:
    """装配 Financial MCP Server；默认使用 build_registry() 的全量 Provider。"""
    return FinancialMCPServer(registry=registry)


def build_knowledge_server(
    manager=None, reranker=None, embedder=None, *, top_k: int = 10
) -> KnowledgeMCPServer:
    """装配 Knowledge MCP Server；检索依赖可注入（测试）。"""
    return KnowledgeMCPServer(manager=manager, reranker=reranker, embedder=embedder, top_k=top_k)


def build_search_server() -> SearchMCPServer:
    """装配 Search MCP Server。"""
    return SearchMCPServer()


__all__ = [
    "build_financial_server",
    "build_knowledge_server",
    "build_search_server",
    "FinancialMCPServer",
    "KnowledgeMCPServer",
    "SearchMCPServer",
]