"""确定性估值引擎（ADR-0010 —— F2 扩展）。

纯 ``decimal.Decimal`` 计算，LLM 永不碰算术（AGENTS.md §3）。提供：
- ``calculate_dcf``：折现自由现金流估值（DCF）；
- ``dcf_sensitivity``：5×5 敏感性网格（WACC × 永续增长率）；
- ``compare_peers``：同业倍数对比（中位数/均值 + 溢价/折价）；
- ``project_growth``：增长率外推。

输入校验复用 :mod:`finsage.financial.engine` 的 ``_to_decimal`` / ``_invalid``
（``None``/非有限/除零 → ``FIN-3102 INVALID_FINANCIAL_INPUT``）。估值函数返回
类型化结果模型，不自动生成 ``Calculation``（与 §22 ``calculate_*`` 约定一致），
溯源由调用方经 ``build_calculation()`` 显式记录。

诚实标注（AGENTS.md §10）：DCF 的 WACC / 永续增长率 / 预测现金流是分析师假设，
引擎只做确定性计算，不背书假设本身。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from .engine import _invalid, _to_decimal

__all__ = [
    "DcfResult",
    "DcfSensitivityResult",
    "PeerComparisonResult",
    "calculate_dcf",
    "dcf_sensitivity",
    "compare_peers",
    "project_growth",
]


class DcfResult(BaseModel):
    """DCF 估值结果（ADR-0010）。"""

    enterprise_value: Decimal
    present_value_fcf: Decimal
    terminal_value: Decimal
    present_value_terminal: Decimal
    wacc: Decimal
    terminal_growth: Decimal


class DcfSensitivityResult(BaseModel):
    """DCF 敏感性网格（WACC × 永续增长率）。"""

    # grid[i][j] = DCF(wacc_values[i], growth_values[j])；无效组合（wacc <= g）为 None。
    grid: list[list[Decimal | None]]
    wacc_values: list[Decimal]
    growth_values: list[Decimal]


class PeerComparisonResult(BaseModel):
    """同业倍数对比结果（ADR-0010）。"""

    metric: str
    company_value: Decimal
    peer_values: list[Decimal]
    peer_median: Decimal
    peer_mean: Decimal
    # 相对同业中位数的溢价/折价（比率，0.25 表示 +25%）。
    premium: Decimal


def _flows(values: Any) -> list[Decimal]:
    flows = [_to_decimal(v, f"free_cash_flows[{i}]") for i, v in enumerate(values)]
    if not flows:
        _invalid("free_cash_flows 为空")
    return flows


def calculate_dcf(free_cash_flows: Any, wacc: Any, terminal_growth: Any) -> DcfResult:
    """折现自由现金流估值（DCF）。

    ``EV = Σ_{t=1..N} FCF_t / (1+wacc)^t + TV / (1+wacc)^N``，
    其中 ``TV = FCF_N · (1+g) / (wacc - g)``。

    边界：空现金流 / ``wacc <= 0`` / ``wacc <= g`` → ``FIN-3102``。
    负现金流允许（部分公司 FCF 为负），终值按公式照算，由调用方解释。
    """
    flows = _flows(free_cash_flows)
    w = _to_decimal(wacc, "wacc")
    g = _to_decimal(terminal_growth, "terminal_growth")
    if w <= Decimal("0"):
        _invalid(f"wacc 必须为正：{w}")
    if w <= g:
        _invalid(f"wacc 必须大于永续增长率：wacc={w} g={g}")

    n = len(flows)
    pv_fcf = Decimal("0")
    for t, fcf in enumerate(flows, start=1):
        pv_fcf += fcf / (Decimal("1") + w) ** t

    tv = flows[-1] * (Decimal("1") + g) / (w - g)
    pv_tv = tv / (Decimal("1") + w) ** n

    return DcfResult(
        enterprise_value=pv_fcf + pv_tv,
        present_value_fcf=pv_fcf,
        terminal_value=tv,
        present_value_terminal=pv_tv,
        wacc=w,
        terminal_growth=g,
    )


def dcf_sensitivity(
    free_cash_flows: Any, wacc_values: Any, growth_values: Any
) -> DcfSensitivityResult:
    """DCF 敏感性网格：对每个 (wacc, growth) 组合计算企业价值。

    无效组合（``wacc <= g``）对应单元格为 ``None``，不静默计算。
    """
    waccs = [_to_decimal(w, f"wacc_values[{i}]") for i, w in enumerate(wacc_values)]
    growths = [_to_decimal(g, f"growth_values[{i}]") for i, g in enumerate(growth_values)]

    grid: list[list[Decimal | None]] = []
    for w in waccs:
        row: list[Decimal | None] = []
        for g in growths:
            if w <= g:
                row.append(None)
            else:
                row.append(calculate_dcf(free_cash_flows, w, g).enterprise_value)
        grid.append(row)

    return DcfSensitivityResult(grid=grid, wacc_values=waccs, growth_values=growths)


def _median(values: list[Decimal]) -> Decimal:
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / Decimal("2")


def compare_peers(metric: str, company_value: Any, peer_values: Any) -> PeerComparisonResult:
    """同业倍数对比：目标倍数 vs 同业倍数的中位数/均值，及相对中位数的溢价/折价。

    边界：空同业列表 → ``FIN-3102``。``premium`` 为比率（0.25 = +25%）。
    """
    company = _to_decimal(company_value, "company_value")
    peers = [_to_decimal(p, f"peer_values[{i}]") for i, p in enumerate(peer_values)]
    if not peers:
        _invalid("peer_values 为空")

    median = _median(peers)
    mean = sum(peers, Decimal("0")) / Decimal(len(peers))
    premium = (
        (company - median) / median if median != Decimal("0") else Decimal("0")
    )

    return PeerComparisonResult(
        metric=metric,
        company_value=company,
        peer_values=peers,
        peer_median=median,
        peer_mean=mean,
        premium=premium,
    )


def project_growth(base_value: Any, growth_rate: Any, periods: int) -> list[Decimal]:
    """增长率外推：``value_t = base · (1+g)^t``，``t = 1..periods``。

    边界：``periods < 0`` 或 ``growth_rate <= -1`` → ``FIN-3102``。
    """
    base = _to_decimal(base_value, "base_value")
    g = _to_decimal(growth_rate, "growth_rate")
    if not isinstance(periods, int) or isinstance(periods, bool) or periods < 0:
        _invalid(f"periods 必须为非负整数：{periods!r}")
    if g <= Decimal("-1"):
        _invalid(f"growth_rate 必须大于 -1：{g}")
    return [base * (Decimal("1") + g) ** t for t in range(1, periods + 1)]
