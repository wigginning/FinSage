"""§22 FROZEN 确定性金融引擎（m05，T501–T507）。

纯 Python + ``Decimal`` 计算；LLM 永不执行公式（§22/§31.3）。所有财务数值
由确定性代码算出（AGENTS.md §3），仅允许经 ``_to_decimal`` 校验后的输入进入。

设计决策（用户 2026-08-24 确认）：
- ``calculate_*`` 遵循 §22 签名返回 ``Decimal``，不自动生成 ``Calculation``；
- 溯源由独立的 ``build_calculation()`` 工厂产出 —— 满足 §22「无 Calculation 对象
  不得产生确定性数字」的阻断约束，由调用方（calculation_node）显式记录；
- ``ComparisonResult`` 字段按用户确认：metric/a/b/delta/delta_pct/period；
- ``convert_unit`` 仅做同币种数量级缩放 + ``pct``(百分比)↔``ratio``；跨币种/维度
  换算需实时汇率，非引擎静态职责，一律抛 ``FIN-3101``（CALCULATION_FAILED）。

边界（§28.1）：除零 / ``None`` / 非有限数值（NaN/Inf）→ ``INVALID_FINANCIAL_INPUT``
（FIN-3102）；``convert_unit`` 不支持的维度/币种换算 → ``CALCULATION_FAILED``（FIN-3101）。
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from finsage.exceptions import CalculationError, ErrorCode
from finsage.observability.trace import uuid_str

from .models import Calculation, ComparisonResult

__all__ = [
    "calculate_gross_margin",
    "calculate_net_margin",
    "calculate_roe",
    "calculate_roa",
    "calculate_current_ratio",
    "calculate_quick_ratio",
    "calculate_debt_ratio",
    "calculate_growth",
    "compare_periods",
    "convert_unit",
    "build_calculation",
    "_RATIO_PRECISION",
]

# 比率类结果的统一精度（P2 修复 L3：避免 28 位 Decimal 被当作"精确值"）。
# 8 位小数与 calculations.output_value 的 NUMERIC(30,8) 对齐，展示稳定可审计。
_RATIO_PRECISION = Decimal("0.00000001")

# 单位 -> 换算基数（相对基础数值的倍数）。取值来自 m03 normalize_unit 词表，
# 仅含同币种数量级与比率维度；跨币种（CNY↔USD 等）不在此表内。
_UNIT_SCALE: dict[str, Decimal] = {
    "CNY": Decimal("1"),
    "CNY_wan": Decimal("1e4"),  # 万 = 1e4 元
    "CNY_yi": Decimal("1e8"),  # 亿 = 1e8 元
    "USD": Decimal("1"),
    "usd_m": Decimal("1e6"),  # 百万美元
    "usd_b": Decimal("1e9"),  # 十亿美元
    "HKD": Decimal("1"),
    "pct": Decimal("0.01"),  # 百分比值 = 0.01 * 基础比率
    "ratio": Decimal("1"),
}

# 单位 -> 维度族（用于拦截跨币种/跨维度换算）。比率维度一律归 "ratio"。
_UNIT_DIMENSION: dict[str, str] = {
    "CNY": "CNY",
    "CNY_wan": "CNY",
    "CNY_yi": "CNY",
    "USD": "USD",
    "usd_m": "USD",
    "usd_b": "USD",
    "HKD": "HKD",
    "pct": "ratio",
    "ratio": "ratio",
}

# 无量纲"比值"的等价写法（"" / "1" 视为 ratio）。
_DIMENSIONLESS_ALIAS = {"", "1", "ratio"}

# 单位词表键（大小写不敏感匹配）：小写 -> 规范键。仅查找，不改写词表。
_UNIT_CANON: dict[str, str] = {k.lower(): k for k in _UNIT_SCALE}


def _invalid(message: str) -> None:
    """抛 FIN-3102：输入无法用于确定性计算。"""
    exc = CalculationError(message)
    exc.code = ErrorCode.INVALID_FINANCIAL_INPUT
    raise exc


def _unsupported(message: str) -> None:
    """抛 FIN-3101：引擎无法完成的计算（如跨币种换算）。"""
    raise CalculationError(message)


def _to_decimal(value: Any, name: str) -> Decimal:
    """把输入规整为有限 Decimal；None/非数值/NaN/Inf → FIN-3102。"""
    if value is None:
        _invalid(f"{name} 为 None")
    if isinstance(value, Decimal):
        dec = value
    else:
        try:
            dec = Decimal(str(value))
        except (ValueError, TypeError, ArithmeticError):
            _invalid(f"{name} 非数值：{value!r}")
    if not dec.is_finite():
        _invalid(f"{name} 非有限数值：{value}")
    return dec


def _ratio(numerator: Decimal, denominator: Decimal, name: str) -> Decimal:
    """确定性除法；除数为零 → FIN-3102。

    结果统一 quantize 到 ``_RATIO_PRECISION`` 位（修复实测 L3：LLM 把 28 位
    Decimal 当"精确值"呈现）。比率类结果在展示/入库前已归一化精度。
    """
    if denominator == Decimal("0"):
        _invalid(f"{name}：分母为零")
    return (numerator / denominator).quantize(_RATIO_PRECISION)


# ---------------------------------------------------------------------------
# T501 比率类
# ---------------------------------------------------------------------------


def calculate_gross_margin(gross_profit, revenue) -> Decimal:
    """毛利率 = 毛利 / 营收。"""
    return _ratio(
        _to_decimal(gross_profit, "gross_profit"),
        _to_decimal(revenue, "revenue"),
        "gross_margin",
    )


def calculate_net_margin(net_income, revenue) -> Decimal:
    """净利率 = 净利润 / 营收。"""
    return _ratio(
        _to_decimal(net_income, "net_income"),
        _to_decimal(revenue, "revenue"),
        "net_margin",
    )


def calculate_roe(net_income, avg_equity) -> Decimal:
    """净资产收益率 = 净利润 / 平均净资产。"""
    return _ratio(
        _to_decimal(net_income, "net_income"),
        _to_decimal(avg_equity, "avg_equity"),
        "roe",
    )


def calculate_roa(net_income, avg_assets) -> Decimal:
    """总资产收益率 = 净利润 / 平均总资产。"""
    return _ratio(
        _to_decimal(net_income, "net_income"),
        _to_decimal(avg_assets, "avg_assets"),
        "roa",
    )


def calculate_current_ratio(current_assets, current_liabilities) -> Decimal:
    """流动比率 = 流动资产 / 流动负债。"""
    return _ratio(
        _to_decimal(current_assets, "current_assets"),
        _to_decimal(current_liabilities, "current_liabilities"),
        "current_ratio",
    )


def calculate_quick_ratio(quick_assets, current_liabilities) -> Decimal:
    """速动比率 = 速动资产 / 流动负债。"""
    return _ratio(
        _to_decimal(quick_assets, "quick_assets"),
        _to_decimal(current_liabilities, "current_liabilities"),
        "quick_ratio",
    )


def calculate_debt_ratio(total_liabilities, total_assets) -> Decimal:
    """资产负债率 = 总负债 / 总资产。"""
    return _ratio(
        _to_decimal(total_liabilities, "total_liabilities"),
        _to_decimal(total_assets, "total_assets"),
        "debt_ratio",
    )


# ---------------------------------------------------------------------------
# T502 增长类
# ---------------------------------------------------------------------------


def calculate_growth(current, previous) -> Decimal:
    """增长率（比率）= (current - previous) / previous；previous 为零 → FIN-3102。"""
    now = _to_decimal(current, "current")
    prev = _to_decimal(previous, "previous")
    return _ratio(now - prev, prev, "growth")


# ---------------------------------------------------------------------------
# T506 期间对比
# ---------------------------------------------------------------------------


def compare_periods(
    metrics_a: Mapping[str, Decimal],
    metrics_b: Mapping[str, Decimal],
    *,
    period_a: str = "",
    period_b: str = "",
) -> list[ComparisonResult]:
    """对两期共有的指标逐一产出对比结果。

    仅对比两期均出现的指标（交集）；``delta = b - a``，``delta_pct`` 为相对变化
    （比率，0.25 表示 +25%）。period 信息由关键字参数提供（FROZEN 位置签名仅两参）。
    """
    results: list[ComparisonResult] = []
    for metric in metrics_a.keys() & metrics_b.keys():
        a = _to_decimal(metrics_a[metric], f"{metric}[a]")
        b = _to_decimal(metrics_b[metric], f"{metric}[b]")
        delta = b - a
        # P2：前值 0 时不再静默置 delta_pct=0，与 calculate_growth 抛错行为一致
        # （审计 §2.6：compare_periods 前值 0 时 delta_pct 静默置 0 不一致）。
        delta_pct = _ratio(delta, a, f"{metric}.delta_pct")
        results.append(
            ComparisonResult(
                metric=metric,
                metric_a=a,
                metric_b=b,
                delta=delta,
                delta_pct=delta_pct,
                period_a=period_a,
                period_b=period_b,
            )
        )
    return results


# ---------------------------------------------------------------------------
# T507 单位换算
# ---------------------------------------------------------------------------


def _unit_key(unit: str) -> str:
    """把单位写法规整为词表规范键；无量纲等价写法归并为 ``ratio``。

    词表键含大小写（如 ``CNY`` / ``usd_b``），故先小写定位再看规范键。
    """
    key = (unit or "").strip().lower()
    if key in _DIMENSIONLESS_ALIAS:
        return "ratio"
    return _UNIT_CANON.get(key, key)


def convert_unit(value, from_unit: str, to_unit: str) -> Decimal:
    """数量级/比例单位换算：``result = value * scale(from) / scale(to)``。

    限制：仅同维度（同币种数量级、或 pct↔ratio）可换算。跨币种/跨维度（如
    CNY→USD、CNY→ratio）需要汇率或非数值映射，引擎不承担 → FIN-3101。
    """
    v = _to_decimal(value, "value")
    src = _unit_key(from_unit)
    dst = _unit_key(to_unit)
    if src not in _UNIT_SCALE or dst not in _UNIT_SCALE:
        _unsupported(f"不支持的单位换算：{from_unit!r} -> {to_unit!r}")
    if src == dst:
        return v
    if _UNIT_DIMENSION[src] != _UNIT_DIMENSION[dst]:
        _unsupported(f"跨币种/维度换算需要汇率，引擎不支持：{from_unit!r} -> {to_unit!r}")
    return v * _UNIT_SCALE[src] / _UNIT_SCALE[dst]


# ---------------------------------------------------------------------------
# T508 溯源工厂
# ---------------------------------------------------------------------------


def build_calculation(
    *,
    formula: str,
    inputs: Mapping[str, Decimal],
    output_value: Decimal,
    output_unit: str | None = None,
    output_currency: str | None = None,
    period: str | None = None,
    source_evidence_ids: list[str] | None = None,
    id: str | None = None,
) -> Calculation:
    """构造 §4.5 Calculation 溯源对象（§22「无 Calculation 不得出确定性数字」）。

    供 calculation_node 在确定性计算完成后显式记录 provenance；id 未给则自动
    生成 UUID4。
    """
    return Calculation(
        id=id or uuid_str(),
        formula=formula,
        inputs=dict(inputs),
        output_value=output_value,
        output_unit=output_unit,
        output_currency=output_currency,
        period=period,
        source_evidence_ids=list(source_evidence_ids or []),
    )