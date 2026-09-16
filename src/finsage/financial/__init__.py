"""确定性金融引擎（m05，§22 FROZEN API）。

导出 §22 冻结函数的便捷入口；引擎与领域模型见
``finsage.financial.engine`` / ``finsage.financial.models``。
"""
from __future__ import annotations

from .engine import (
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
from .models import Calculation, ComparisonResult
from .valuation import (
    DcfResult,
    DcfSensitivityResult,
    PeerComparisonResult,
    calculate_dcf,
    compare_peers,
    dcf_sensitivity,
    project_growth,
)

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
    "Calculation",
    "ComparisonResult",
    "calculate_dcf",
    "dcf_sensitivity",
    "compare_peers",
    "project_growth",
    "DcfResult",
    "DcfSensitivityResult",
    "PeerComparisonResult",
]