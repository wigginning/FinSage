"""T404c/d/e 三大报表的指标-报表类别映射（§12.3 + 工程补全）。

规格只冻结工具名与入参示例，未给报表归属的过滤规则。
m04 采用用户选定的「按 metric 类别过滤」方案：将 Provider 产出的 FinancialMetric
按其规范化 metric 名确定性归到 income / balance / cash_flow。

归类规则为工程补全（AGENTS.md §10 诚实标注，不伪装冻结）：
- 命中显式映射表 -> 对应报表类别；
- 未命中 -> 返回 None（不放任静默分组，交由上层决定是否透出）。
归类用规范 metric 小写名（normalize_metric 的别名已收敛，如 revenue/net_income）。
"""
from __future__ import annotations

from typing import Literal

StatementKind = Literal["income", "balance", "cash_flow"]

# 利润表指标（income）。
_INCOME_METRICS = frozenset(
    {
        "revenue",
        "net_income",
        "gross_margin",
        "gross_profit",
        "operating_profit",
        "operating_margin",
        "net_margin",
        "eps",
        "diluted_eps",
        "ebit",
        "ebitda",
        "income_tax",
        "interest_expense",
    }
)

# 资产负债表指标（balance）。
_BALANCE_METRICS = frozenset(
    {
        "total_assets",
        "total_liabilities",
        "equity",
        "cash",
        "cash_and_equivalents",
        "inventory",
        "accounts_receivable",
        "accounts_payable",
        "current_assets",
        "current_liabilities",
        "long_term_debt",
        "short_term_debt",
    }
)

# 现金流量表指标（cash_flow）。
_CASHFLOW_METRICS = frozenset(
    {
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "free_cash_flow",
        "capex",
        "depreciation_amortization",
    }
)


def classify_metric(metric: str) -> StatementKind | None:
    """把一个规范化 metric 名归到报表类别；未命中返回 None。"""
    key = metric.strip().lower()
    if key in _INCOME_METRICS:
        return "income"
    if key in _BALANCE_METRICS:
        return "balance"
    if key in _CASHFLOW_METRICS:
        return "cash_flow"
    return None


__all__ = ["classify_metric", "StatementKind"]