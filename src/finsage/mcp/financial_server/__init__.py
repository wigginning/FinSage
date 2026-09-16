"""Financial MCP Server（T401 + T404a–g，§12）。

Server：``finsage-financial-mcp``。工具集合与规格 §12.1 冻结一致，共 7 个：
get_stock_quote / get_financial_statements / get_income_statement / get_balance_sheet /
get_cash_flow / get_company_profile / get_news。

接入规则（AGENTS.md §4）：
- 本 Server 只与 Provider Registry 交互，永不直接 import 底层 SDK；
- 三大报表工具（get_income_statement 等）复用 get_financials，并按 metric 类别
  （metrics.classify_metric）过滤出对应报表的指标（T404c/d/e，按用户选定方案）。

实现基于 FastMCP（mcp 包）。FastMCP 实例名即 MCP server 名。
"""
from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from finsage.observability.logger import get_logger, io_point
from finsage.providers.finance import ProviderRegistry, build_registry

from .metrics import classify_metric

logger = get_logger(__name__)

# Server 名与规格 §12.1 冻结一致。
SERVER_NAME = "finsage-financial-mcp"


def _asdict(value: Any) -> dict:
    """把 pydantic/domain 对象转 JSON 友好的 dict。"""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


@io_point("mcp.financial", "get_stock_quote")
async def _get_stock_quote(registry: ProviderRegistry, symbol: str, market: str) -> dict:
    """§12.2：实时行情。仅经 Registry 按能力路由 + failover。"""
    return _asdict(
        await registry.invoke(
            lambda p: p.get_quote(symbol, market), operation="quote", market=market
        )
    )


@io_point("mcp.financial", "get_financial_statements")
async def _get_financial_statements(
    registry: ProviderRegistry, symbol: str, market: str, period: str
) -> dict:
    """§12.3：财务指标全集。Output: {items: [FinancialMetric]}。"""
    items = await registry.invoke(
        lambda p: p.get_financials(symbol, market, period),
        operation="financials",
        market=market,
    )
    return {"items": [_asdict(item) for item in items]}


async def _statement(
    registry: ProviderRegistry,
    symbol: str,
    market: str,
    period: str,
    kind: Literal["income", "balance", "cash_flow"],
) -> dict:
    """按 metric 类别过滤 get_financials 产出；输出结构与 §12.3 一致。"""
    items = await registry.invoke(
        lambda p: p.get_financials(symbol, market, period),
        operation="financials",
        market=market,
    )
    filtered = [m for m in items if classify_metric(getattr(m, "metric", "")) == kind]
    return {"items": [_asdict(item) for item in filtered]}


@io_point("mcp.financial", "get_income_statement")
async def _get_income_statement(
    registry: ProviderRegistry, symbol: str, market: str, period: str
) -> dict:
    """利润表（§12.3，按 metric 类别过滤）。"""
    return await _statement(registry, symbol, market, period, "income")


@io_point("mcp.financial", "get_balance_sheet")
async def _get_balance_sheet(
    registry: ProviderRegistry, symbol: str, market: str, period: str
) -> dict:
    """资产负债表（§12.3，按 metric 类别过滤）。"""
    return await _statement(registry, symbol, market, period, "balance")


@io_point("mcp.financial", "get_cash_flow")
async def _get_cash_flow(
    registry: ProviderRegistry, symbol: str, market: str, period: str
) -> dict:
    """现金流量表（§12.3，按 metric 类别过滤）。"""
    return await _statement(registry, symbol, market, period, "cash_flow")


@io_point("mcp.financial", "get_company_profile")
async def _get_company_profile(registry: ProviderRegistry, symbol: str, market: str) -> dict:
    """§12.4：公司概况。"""
    return _asdict(
        await registry.invoke(
            lambda p: p.get_company_profile(symbol, market),
            operation="company_profile",
            market=market,
        )
    )


@io_point("mcp.financial", "get_news")
async def _get_news(registry: ProviderRegistry, symbol: str, market: str, limit: int) -> dict:
    """§12.5：公司新闻。"""
    items = await registry.invoke(
        lambda p: p.get_news(symbol, market, limit),
        operation="news",
        market=market,
    )
    return {"items": [_asdict(item) for item in items]}


class FinancialMCPServer:
    """封装 FastMCP 并注入 Provider Registry，便于单测替换依赖。

    工具以绑定的闭包函数注册到 FastMCP，调用时使用实例注入的 registry，
    确保「金融工具只经 Provider Registry」（验收 DoD）。
    """

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or build_registry()
        self.app = FastMCP(SERVER_NAME)
        self._register()

    def _register(self) -> None:
        r = self.registry

        async def quote(symbol: str, market: str) -> dict:
            return await _get_stock_quote(r, symbol, market)

        async def statements(symbol: str, market: str, period: str) -> dict:
            return await _get_financial_statements(r, symbol, market, period)

        async def income(symbol: str, market: str, period: str) -> dict:
            return await _get_income_statement(r, symbol, market, period)

        async def balance(symbol: str, market: str, period: str) -> dict:
            return await _get_balance_sheet(r, symbol, market, period)

        async def cash_flow(symbol: str, market: str, period: str) -> dict:
            return await _get_cash_flow(r, symbol, market, period)

        async def profile(symbol: str, market: str) -> dict:
            return await _get_company_profile(r, symbol, market)

        async def news(symbol: str, market: str, limit: int = 20) -> dict:
            return await _get_news(r, symbol, market, limit)

        self.app.add_tool(quote, name="get_stock_quote", description="实时行情（§12.2）")
        self.app.add_tool(
            statements, name="get_financial_statements", description="财务指标全集（§12.3）"
        )
        self.app.add_tool(income, name="get_income_statement", description="利润表（§12.3）")
        self.app.add_tool(balance, name="get_balance_sheet", description="资产负债表（§12.3）")
        self.app.add_tool(cash_flow, name="get_cash_flow", description="现金流量表（§12.3）")
        self.app.add_tool(profile, name="get_company_profile", description="公司概况（§12.4）")
        self.app.add_tool(news, name="get_news", description="公司新闻（§12.5）")

    async def list_tools(self) -> list[str]:
        """列出已注册工具名（供测试/诊断）。"""
        tools = await self.app.list_tools()
        return [t.name for t in tools]

    def serve(
        self, *, transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    ) -> None:
        """启动 MCP server 进程（ADR-0021：作为外部工具面独立对外）。

        ``transport``：``stdio``（默认，供本地 MCP 客户端/子进程）/
        ``sse`` / ``streamable-http``（远程）。不替换 graph 内部 Milvus 直连检索
        （冻结架构），仅对外暴露工具能力。
        """
        self.app.run(transport=transport)


__all__ = ["FinancialMCPServer", "SERVER_NAME", "classify_metric"]