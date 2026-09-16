"""Provider 域：契约、实现与装配（m03）。

对外暴露统一入口：
- `build_registry()` 按 §10.1 路由声明注册四个数据源 Provider；
- 上层（MCP/Agent）只与本包 Registry 交互，绝不直接触碰底层 SDK（AGENTS.md §4）。

能力声明更新需保持与 normalize/conflict 的归一化边界一致。
"""

from __future__ import annotations

# ---- 具体实现（SDK 层）----
from .akshare import AKShareProvider
from .ashare import AshareProvider
from .baostock import BaoStockProvider
from .base import BaseProvider, FinancialDataProvider, ensure_symbol_market, utcnow
from .conflict import Consistency, FinancialValue, compare
from .domain import (
    CompanyProfile,
    FinancialMetric,
    NewsItem,
    ProviderHealth,
    Quote,
)
from .efinance import EFinanceProvider
from .normalize import (
    normalize_currency,
    normalize_definition,
    normalize_market,
    normalize_metric,
    normalize_period,
    normalize_symbol,
    normalize_unit,
)
from .pytdx import PytdxProvider
from .registry import Capabilities, ProviderRegistry
from .resilience import CircuitBreaker, retry
from .sina import SinaQuoteProvider
from .tencent import TencentQuoteProvider
from .tushare import TushareProvider
from .yfinance_provider import YFinanceProvider


def build_registry() -> ProviderRegistry:
    """装配默认 Provider Registry（§10.1 能力声明 + 优先级路由）。

    优先级（priority 越小越优先，对齐 daily_stock_analysis 语义）：
    - 可用/免费/无 token 源给低值（高优先）：efinance(0) / akshare(1) /
      tencent(2) / sina(3) / pytdx(4) / baostock(5)；
    - 不可用源给高值（低优先）：ashare(10，SDK 未安装)、tushare(90，需 token)，
      使 failover 先走可用源，不可用源仅在配置就绪时兜底。

    东财反爬补丁为 opt-in：仅当 FIN_ENABLE_EASTMONEY_PATCH=true 时传给
    efinance/akshare Provider（见 eastmoney_patch 合规说明）。
    """
    from finsage.settings import get_settings

    enable_patch = get_settings().enable_eastmoney_patch
    registry = ProviderRegistry()
    registry.register(
        EFinanceProvider(enable_eastmoney_patch=enable_patch),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "financials": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=0,
    )
    registry.register(
        AKShareProvider(enable_eastmoney_patch=enable_patch),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "financials": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
            "news": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=1,
    )
    registry.register(
        TencentQuoteProvider(),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=2,
    )
    # Sina 免费行情源：CN quote 交叉校验候选（与 Tencent 同口径，无 SDK/token）。
    registry.register(
        SinaQuoteProvider(),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=3,
    )
    registry.register(
        PytdxProvider(),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "financials": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=4,
    )
    registry.register(
        BaoStockProvider(),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "financials": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=5,
    )
    # Ashare SDK 未安装（不可用）：低优先兜底，避免抢占可用源。
    registry.register(
        AshareProvider(),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=10,
    )
    registry.register(
        YFinanceProvider(),
        capabilities={
            "quote": ["US", "HK"],
            "financials": ["US", "HK"],
            "company_profile": ["US", "HK"],
            "news": ["US", "HK"],
        },
        priority=1,
    )
    # Tushare 需 token（不可用）：低优先兜底，token 配置就绪时才参与 failover。
    registry.register(
        TushareProvider(),
        capabilities={
            "quote": ["CN", "CN.SH", "CN.SZ"],
            "financials": ["CN", "CN.SH", "CN.SZ"],
            "company_profile": ["CN", "CN.SH", "CN.SZ"],
        },
        priority=90,
    )
    return registry


__all__ = [
    # 契约/基类
    "FinancialDataProvider",
    "BaseProvider",
    "ProviderRegistry",
    "Capabilities",
    "CircuitBreaker",
    "retry",
    # 具体实现
    "AKShareProvider",
    "BaoStockProvider",
    "AshareProvider",
    "YFinanceProvider",
    "TencentQuoteProvider",
    "SinaQuoteProvider",
    "TushareProvider",
    "EFinanceProvider",
    "PytdxProvider",
    "build_registry",
    # 域模型
    "Quote",
    "FinancialMetric",
    "CompanyProfile",
    "NewsItem",
    "ProviderHealth",
    # 归一化
    "normalize_symbol",
    "normalize_market",
    "normalize_metric",
    "normalize_currency",
    "normalize_unit",
    "normalize_period",
    "normalize_definition",
    "ensure_symbol_market",
    "utcnow",
    # 冲突比对
    "compare",
    "FinancialValue",
    "Consistency",
]