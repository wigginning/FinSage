"""P2 基础设施接线测试（离线，不依赖 Milvus/MySQL/Provider SDK）。

验证：
- P2-A 检索开关：关闭→None，开启→可调用（不实际连接 Milvus）；
- P2-B 财务开关：关闭→None，开启→适配器正确聚合 registry 产出；节点对
  MarketDataUnavailableError 等不再击穿整图；
- P2-C 仓储选择：默认内存，enable_persistence→MySQL 审计仓储（不连库）。
"""
from __future__ import annotations

from finsage.api.app import AuditStore, EvidenceStore, build_stores
from finsage.api.mysql_stores import MySQLAuditStore, MySQLFileStore
from finsage.api.runner_real import (
    build_default_workflow_deps,
    build_financial,
    build_retriever,
)
from finsage.models.entities import Entity
from finsage.settings import Settings


# ---- P2-A 检索 ---------------------------------------------------------------
async def test_build_retriever_disabled_returns_none():
    assert build_retriever(Settings(enable_retrieval=False)) is None


async def test_build_retriever_enabled_returns_callable():
    retr = build_retriever(Settings(enable_retrieval=True))
    assert callable(retr)  # 仅校验装配，不调用（避免加载 BGE-M3 / 连接 Milvus）


# ---- P2-B 财务 ---------------------------------------------------------------
class _FakeRegistry:
    """测试用假 registry：忽略 factory，按 market 返回占位指标。"""

    async def invoke(self, factory, *, operation, market, retries=1):
        return [{"market": market, "metric": "revenue", "value": 100}]


async def test_build_financial_disabled_returns_none():
    assert build_financial(Settings(enable_financial=False)) is None


async def test_build_financial_enabled_aggregates_registry():
    fn = build_financial(Settings(enable_financial=True), registry=_FakeRegistry())
    assert callable(fn)
    entities = [Entity(type="ticker", value="600000", normalized_value="600000", market="CN")]
    out = await fn("某公司的营收", entities)
    assert out == [{"market": "CN", "metric": "revenue", "value": 100}]


# ---- P2-B 回归：ProviderRegistry.invoke 会把 provider 实例喂给 factory ----
# 旧实现 partial(lambda p, s, m: p.get_financials(s, m, "FY"), sym, market) 把 sym（字符串）
# 错塞进 provider 槽位，真实 invoke 注入 provider 后触发
# AttributeError: 'str' object has no attribute 'get_financials'。以下假 registry 复刻
# invoke 的关键契约（factory(provider)），能稳定复现并锁定该回归。
class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_financials(self, symbol, market, period):
        self.calls.append((symbol, market, period))
        return [{"symbol": symbol, "period": period, "value": 1}]


class _RealisticRegistry:
    async def invoke(self, factory, *, operation, market, retries=1):
        provider = _FakeProvider()
        return await factory(provider)


async def test_build_financial_passes_provider_not_symbol():
    fn = build_financial(Settings(enable_financial=True), registry=_RealisticRegistry())
    assert callable(fn)
    entities = [Entity(type="ticker", value="300750", normalized_value="300750", market="CN")]
    out = await fn("宁德时代储能业务", entities)
    assert len(out) == 1
    assert out[0]["symbol"] == "300750"
    assert out[0]["period"] == "FY"


# ---- P2 装配到 WorkflowDeps --------------------------------------------------
async def test_default_workflow_deps_respects_flags():
    # 显式关闭两个开关，避免受 .env（FIN_ENABLE_RETRIEVAL / FIN_ENABLE_FINANCIAL）影响。
    off = build_default_workflow_deps(Settings(enable_retrieval=False, enable_financial=False))
    assert off.retrieve is None and off.financial is None

    on = build_default_workflow_deps(
        Settings(enable_retrieval=True, enable_financial=True)
    )
    assert callable(on.retrieve) and callable(on.financial)


# ---- 节点对 MarketDataUnavailableError 的兜底（不击穿整图）------------------
async def test_financial_node_maps_provider_error_to_code():
    from finsage.exceptions import MarketDataUnavailableError
    from finsage.workflows.nodes import WorkflowDeps, make_financial_data

    async def _boom(q, entities):
        raise MarketDataUnavailableError("no provider")

    deps = WorkflowDeps(financial=_boom)
    node = make_financial_data(deps)
    result = await node({"normalized_query": "x", "entities": []})
    # MarketDataUnavailableError.code.value == "FIN-2201"（诚实映射，不击穿整图）。
    assert result.get("error_code") == "FIN-2201"


# ---- P2-C 仓储选择 -----------------------------------------------------------
def test_build_stores_default_in_memory():
    stores = build_stores(Settings())
    assert isinstance(stores.audit, AuditStore)
    assert not isinstance(stores.audit, MySQLAuditStore)


def test_build_stores_persistence_selects_mysql_audit():
    stores = build_stores(Settings(enable_persistence=True))
    # 审计落 MySQL、文档上传元数据落 MySQL（ADR-0007）；证据暂保留内存（P2-C.2 后续）。
    # 构造不连库，验证选择正确即可。
    assert isinstance(stores.audit, MySQLAuditStore)
    assert isinstance(stores.files, MySQLFileStore)
    assert isinstance(stores.evidence, EvidenceStore)
