"""m05 确定性金融引擎单测（T509，§28.1 边界）。

覆盖 §22 全部冻结函数：比率类、增长、期间对比、单位换算、Calculation 溯源工厂，
以及除零 / 无效输入 / 跨币种换算的 FIN-3101 / FIN-3102 边界。
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from finsage.exceptions import CalculationError, ErrorCode
from finsage.financial import (
    Calculation,
    ComparisonResult,
    build_calculation,
    calculate_current_ratio,
    calculate_debt_ratio,
    calculate_gross_margin,
    calculate_growth,
    calculate_net_margin,
    calculate_quick_ratio,
    calculate_roa,
    calculate_roe,
    compare_periods,
    convert_unit,
)

D = Decimal


# ---- T501 比率类 ----
def test_gross_margin():
    assert calculate_gross_margin(D("40"), D("100")) == D("0.4")


def test_net_margin():
    assert calculate_net_margin(D("25"), D("100")) == D("0.25")


def test_roe():
    assert calculate_roe(D("10"), D("200")) == D("0.05")


def test_roa():
    assert calculate_roa(D("10"), D("400")) == D("0.025")


def test_current_ratio():
    assert calculate_current_ratio(D("200"), D("100")) == D("2")


def test_quick_ratio():
    assert calculate_quick_ratio(D("50"), D("100")) == D("0.5")


def test_debt_ratio():
    assert calculate_debt_ratio(D("30"), D("100")) == D("0.3")


def test_ratio_accepts_numeric_types():
    assert calculate_gross_margin(40.0, 100) == D("0.4")
    assert isinstance(calculate_gross_margin("40", "100"), Decimal)


# ---- T502 增长类 ----
def test_growth_positive():
    assert calculate_growth(D("120"), D("100")) == D("0.2")


def test_growth_negative():
    assert calculate_growth(D("80"), D("100")) == D("-0.2")


def test_growth_zero_previous_raises_invalid():
    with pytest.raises(CalculationError) as ei:
        calculate_growth(D("5"), D("0"))
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


# ---- 除零 / 无效输入边界（§28.1）----
@pytest.mark.parametrize(
    "fn,args",
    [
        (calculate_gross_margin, (D("1"), D("0"))),
        (calculate_net_margin, (D("1"), D("0"))),
        (calculate_roe, (D("1"), D("0"))),
        (calculate_roa, (D("1"), D("0"))),
        (calculate_current_ratio, (D("1"), D("0"))),
        (calculate_quick_ratio, (D("1"), D("0"))),
        (calculate_debt_ratio, (D("1"), D("0"))),
    ],
)
def test_division_by_zero_raises_invalid(fn, args):
    with pytest.raises(CalculationError) as ei:
        fn(*args)
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


@pytest.mark.parametrize(
    "fn,args",
    [
        (calculate_gross_margin, (None, D("1"))),
        (calculate_gross_margin, ("abc", D("1"))),
        (calculate_net_margin, (float("nan"), D("1"))),
        (calculate_roe, (object(), D("1"))),
    ],
)
def test_invalid_input_raises_invalid(fn, args):
    with pytest.raises(CalculationError) as ei:
        fn(*args)
    assert ei.value.code == ErrorCode.INVALID_FINANCIAL_INPUT


# ---- T506 期间对比 ----
def test_compare_periods_intersection():
    a = {"revenue": D("100"), "net_income": D("10"), "only_a": D("1")}
    b = {"revenue": D("125"), "net_income": D("15")}
    out = compare_periods(a, b, period_a="2023", period_b="2024")
    by_metric = {r.metric: r for r in out}
    assert set(by_metric) == {"revenue", "net_income"}  # only_a 不在交集
    rev = by_metric["revenue"]
    assert isinstance(rev, ComparisonResult)
    assert rev.metric_a == D("100") and rev.metric_b == D("125")
    assert rev.delta == D("25") and rev.delta_pct == D("0.25")
    assert rev.period_a == "2023" and rev.period_b == "2024"


def test_compare_periods_default_periods_empty():
    out = compare_periods({"x": D("2")}, {"x": D("4")})
    assert out[0].period_a == "" and out[0].period_b == ""


def test_compare_periods_zero_base_gives_zero_pct():
    """P2：前值为 0 时 delta_pct 应抛 FIN-3102（与 calculate_growth 一致），
    不再静默置 0（审计 §2.6：不一致行为已修复）。"""
    with pytest.raises(CalculationError) as exc:
        compare_periods({"x": D("0")}, {"x": D("3")})
    assert exc.value.code is ErrorCode.INVALID_FINANCIAL_INPUT


def test_ratio_quantized_to_eight_places():
    """P2/L3：比率类结果统一 quantize 到 8 位小数，避免 28 位 Decimal 当精确值。"""
    # 1/3 会产生无限不循环小数；量化后应稳定为 8 位。
    out = calculate_net_margin(D("1"), D("3"))
    assert out == D("0.33333333")
    # 2/3 -> 0.66666667（第 9 位四舍五入）。
    out2 = calculate_net_margin(D("2"), D("3"))
    assert out2 == D("0.66666667")


def test_compare_periods_returns_empty_for_disjoint():
    assert compare_periods({"a": D("1")}, {"b": D("2")}) == []


# ---- T507 单位换算 ----
def test_convert_cny_to_cny_yi():
    assert convert_unit(D("123000000"), "CNY", "CNY_yi") == D("1.23")


def test_convert_cny_wan_to_cny():
    assert convert_unit(D("5"), "CNY_wan", "CNY") == D("50000")


def test_convert_pct_to_ratio():
    assert convert_unit(D("12.5"), "pct", "ratio") == D("0.125")


def test_convert_ratio_to_pct():
    assert convert_unit(D("0.125"), "ratio", "pct") == D("12.5")


def test_convert_same_unit_noop():
    assert convert_unit(D("7"), "CNY", "CNY") == D("7")


def test_convert_usd_m_to_usd():
    assert convert_unit(D("3"), "usd_m", "USD") == D("3000000")


def test_convert_cross_currency_raises_calc_failed():
    with pytest.raises(CalculationError) as ei:
        convert_unit(D("1"), "CNY", "USD")
    assert ei.value.code == ErrorCode.CALCULATION_FAILED


def test_convert_unknown_unit_raises_calc_failed():
    with pytest.raises(CalculationError) as ei:
        convert_unit(D("1"), "CNY", "share")
    assert ei.value.code == ErrorCode.CALCULATION_FAILED


# ---- T508 Calculation 模型 / 溯源工厂 ----
def test_calculation_model_defaults():
    calc = Calculation(formula="a/b", inputs={"a": D("4"), "b": D("2")}, output_value=D("2"))
    assert calc.id and len(calc.id) == 36
    assert calc.output_unit is None and calc.output_currency is None
    assert calc.period is None and calc.source_evidence_ids == []


def test_build_calculation_rich():
    calc = build_calculation(
        formula="net_income / revenue",
        inputs={"net_income": D("10"), "revenue": D("100")},
        output_value=D("0.1"),
        output_unit="pct",
        period="2024",
        source_evidence_ids=["ev1", "ev2"],
    )
    assert isinstance(calc, Calculation)
    assert len(calc.id) == 36
    assert calc.formula == "net_income / revenue"
    assert calc.output_value == D("0.1")
    assert calc.output_unit == "pct" and calc.period == "2024"
    assert calc.source_evidence_ids == ["ev1", "ev2"]


def test_build_calculation_fixed_id():
    calc = build_calculation(formula="x", inputs={}, output_value=D("1"), id="fixed-123")
    assert calc.id == "fixed-123"


def test_calculation_requires_formula_and_inputs():
    with pytest.raises(ValidationError):
        Calculation()  # type: ignore[call-arg]