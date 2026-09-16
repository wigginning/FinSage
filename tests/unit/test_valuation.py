"""ADR-0010 确定性估值引擎单测。

覆盖 DCF / 敏感性网格 / 同业对比 / 增长率外推，以及除零、空输入、无效参数
（wacc<=0、wacc<=g、负增长率）的 FIN-3102 边界。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from finsage.exceptions import CalculationError, ErrorCode
from finsage.financial import (
    DcfResult,
    DcfSensitivityResult,
    PeerComparisonResult,
    calculate_dcf,
    compare_peers,
    dcf_sensitivity,
    project_growth,
)

D = Decimal


# ---- DCF ----
def test_dcf_single_flow_exact():
    # FCF=[100], wacc=0.25, g=0.05：
    # PV_FCF = 100/1.25 = 80；TV = 100*1.05/0.20 = 525；PV_TV = 525/1.25 = 420；EV = 500。
    r = calculate_dcf([D("100")], D("0.25"), D("0.05"))
    assert isinstance(r, DcfResult)
    assert r.enterprise_value == D("500")
    assert r.present_value_fcf == D("80")
    assert r.terminal_value == D("525")
    assert r.present_value_terminal == D("420")


def test_dcf_multi_year():
    # FCF=[100,100], wacc=0.25, g=0.05：
    # PV_FCF = 80 + 64 = 144；TV = 525；PV_TV = 525/1.5625 = 336；EV = 480。
    r = calculate_dcf([D("100"), D("100")], D("0.25"), D("0.05"))
    assert r.enterprise_value == D("480")
    assert r.present_value_fcf == D("144")


def test_dcf_accepts_numeric_types():
    r = calculate_dcf([100], 0.25, 0.05)
    assert r.enterprise_value == D("500")


def test_dcf_negative_fcf_allowed():
    # 负现金流允许：终值按公式照算，由调用方解释。
    r = calculate_dcf([D("-100")], D("0.25"), D("0.05"))
    assert r.enterprise_value == D("-500")


@pytest.mark.parametrize(
    "flows,wacc,g",
    [
        ([], D("0.25"), D("0.05")),  # 空现金流
        ([D("100")], D("0"), D("0.05")),  # wacc = 0
        ([D("100")], D("-0.1"), D("0.05")),  # wacc < 0
        ([D("100")], D("0.05"), D("0.05")),  # wacc == g
        ([D("100")], D("0.05"), D("0.10")),  # wacc < g
    ],
)
def test_dcf_invalid_params_raise_invalid(flows, wacc, g):
    with pytest.raises(CalculationError) as ei:
        calculate_dcf(flows, wacc, g)
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


def test_dcf_none_input_raises_invalid():
    with pytest.raises(CalculationError) as ei:
        calculate_dcf([None], D("0.25"), D("0.05"))
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


# ---- 敏感性网格 ----
def test_dcf_sensitivity_grid_shape():
    waccs = [D("0.20"), D("0.25"), D("0.30"), D("0.35"), D("0.40")]
    growths = [D("0.01"), D("0.02"), D("0.03"), D("0.04"), D("0.05")]
    r = dcf_sensitivity([D("100")], waccs, growths)
    assert isinstance(r, DcfSensitivityResult)
    assert len(r.grid) == 5 and all(len(row) == 5 for row in r.grid)
    assert r.wacc_values == waccs and r.growth_values == growths
    # 中心格 = DCF(wacc=0.30, g=0.03)。
    assert r.grid[2][2] == calculate_dcf([D("100")], D("0.30"), D("0.03")).enterprise_value


def test_dcf_sensitivity_marks_invalid_cell_none():
    # wacc <= g 的组合无效 -> None；wacc > g 的组合有效。
    r = dcf_sensitivity([D("100")], [D("0.05"), D("0.10")], [D("0.02"), D("0.10")])
    assert r.grid[0][0] is not None  # 0.05 > 0.02
    assert r.grid[0][1] is None  # 0.05 <= 0.10
    assert r.grid[1][0] is not None  # 0.10 > 0.02
    assert r.grid[1][1] is None  # 0.10 == 0.10


# ---- 同业对比 ----
def test_compare_peers_even_count():
    r = compare_peers("P/E", D("30"), [D("10"), D("20"), D("30"), D("40")])
    assert isinstance(r, PeerComparisonResult)
    assert r.metric == "P/E"
    assert r.peer_median == D("25")  # (20+30)/2
    assert r.peer_mean == D("25")
    assert r.premium == D("0.2")  # (30-25)/25


def test_compare_peers_odd_count():
    r = compare_peers("P/B", D("2"), [D("1"), D("2"), D("3")])
    assert r.peer_median == D("2")
    assert r.peer_mean == D("2")
    assert r.premium == D("0")


def test_compare_peers_discount_negative_premium():
    r = compare_peers("P/E", D("8"), [D("10"), D("10")])
    assert r.premium == D("-0.2")


def test_compare_peers_zero_median_gives_zero_premium():
    r = compare_peers("P/E", D("5"), [D("0"), D("0")])
    assert r.premium == D("0")


def test_compare_peers_empty_raises_invalid():
    with pytest.raises(CalculationError) as ei:
        compare_peers("P/E", D("10"), [])
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


# ---- 增长率外推 ----
def test_project_growth():
    assert project_growth(D("100"), D("0.10"), 3) == [D("110"), D("121"), D("133.1")]


def test_project_growth_zero_periods_empty():
    assert project_growth(D("100"), D("0.10"), 0) == []


def test_project_growth_negative_periods_raises_invalid():
    with pytest.raises(CalculationError) as ei:
        project_growth(D("100"), D("0.10"), -1)
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


def test_project_growth_rate_le_minus_one_raises_invalid():
    with pytest.raises(CalculationError) as ei:
        project_growth(D("100"), D("-1"), 3)
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT
