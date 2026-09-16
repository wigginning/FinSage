"""T312 Provider conflict detection（§11 — Cross-Provider Validation）。

在比较前完成七类归一化（normalize 模块），再按比较键
(company, ticker, market, metric, period, currency, unit, definition) 比对，
产出一致性状态：MATCH / CONFLICT / INSUFFICIENT / NOT_COMPARABLE。

规则（§11）：
  MATCH          -> confidence can increase
  CONFLICT       -> high confidence forbidden
  INSUFFICIENT   -> warning
  NOT_COMPARABLE -> do not compare

金融比对是确定性 Python 逻辑，不依赖 LLM（AGENTS.md §3）。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from .normalize import (
    normalize_currency,
    normalize_definition,
    normalize_market,
    normalize_metric,
    normalize_period,
    normalize_symbol,
    normalize_unit,
)

Consistency = Literal["MATCH", "CONFLICT", "INSUFFICIENT", "NOT_COMPARABLE"]

# 可容忍的相对误差上限；超过即视为数值冲突（工程默认，可配置覆盖）。
_TOLERANCE = Decimal("0.005")  # 0.5%


@dataclass(frozen=True)
class FinancialValue:
    """一条待比对的财务数值（比较键 + 原始值）。"""

    company: str
    ticker: str
    market: str
    metric: str
    value: Decimal
    currency: str | None = None
    unit: str | None = None
    period: str = ""
    definition: str | None = None


def _norm(metric: FinancialValue) -> tuple:
    """归一化比较键（不含 value）。"""
    return (
        metric.company.strip().lower(),
        normalize_symbol(metric.ticker),
        normalize_market(metric.market),
        normalize_metric(metric.metric),
        normalize_period(metric.period or ""),
        normalize_currency(metric.currency or ""),
        normalize_unit(metric.unit or ""),
        normalize_definition(metric.definition or ""),
    )


def _has_all_keys(v: FinancialValue) -> bool:
    """比较键全部非空才可可靠比对；任一缺失视为信息不足。

    必要键：company/ticker/market/metric/currency/unit/period。
    ``definition`` 是可选细分维度，缺省不阻断比对（否则 compare 恒返回
    INSUFFICIENT，即系统审计指出的死代码根因）。
    """
    keys = (
        "company",
        "ticker",
        "market",
        "metric",
        "currency",
        "unit",
        "period",
    )
    return all((getattr(v, field) or "").strip() for field in keys)


def detect_metric_conflicts(metrics: list[Any]) -> list[str]:
    """对同一 (ticker, market, metric, period) 的跨 Provider 数值做冲突检测（P2）。

    把 ``conflict.compare`` 从死代码接线到工作流：同一键下不同 ``source`` 的指标
    两两比对，产出 CONFLICT 描述（"冲突不得静默忽略"，AGENTS.md §3）。

    返回冲突描述列表（如 ``"CONFLICT:ticker.metric.period.sourceA/sourceB"``）；
    无冲突或信息不足返回空列表。
    """
    from collections import defaultdict

    groups: dict[tuple, list[Any]] = defaultdict(list)
    for m in metrics:
        ticker = getattr(m, "ticker", "") or ""
        market = getattr(m, "market", "") or ""
        metric = getattr(m, "metric", "") or ""
        period = getattr(m, "period", "") or ""
        currency = getattr(m, "currency", "") or ""
        source = getattr(m, "source", "") or ""
        if not (ticker and market and metric and period and currency and source):
            continue
        groups[(ticker, market, metric, period)].append((m, source))

    conflicts: list[str] = []
    for (ticker, market, metric, period), items in groups.items():
        # 仅单一来源无冲突；多个来源两两比对。
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, sa = items[i]
                b, sb = items[j]
                if sa == sb:
                    continue
                fv_a = FinancialValue(
                    company=getattr(a, "company", "") or "",
                    ticker=ticker,
                    market=market,
                    metric=metric,
                    value=a.value,
                    currency=getattr(a, "currency", None),
                    unit=getattr(a, "unit", None),
                    period=period,
                )
                fv_b = FinancialValue(
                    company=getattr(b, "company", "") or "",
                    ticker=ticker,
                    market=market,
                    metric=metric,
                    value=b.value,
                    currency=getattr(b, "currency", None),
                    unit=getattr(b, "unit", None),
                    period=period,
                )
                if compare(fv_a, fv_b) == "CONFLICT":
                    conflicts.append(f"CONFLICT:{ticker}.{metric}.{period}.{sa}/{sb}")
    return conflicts


__all__ = ["FinancialValue", "compare", "detect_metric_conflicts", "Consistency"]


def compare(left: FinancialValue, right: FinancialValue) -> Consistency:
    """比对两条财务数值，返回一致性状态。

    - 比较键任一缺失/非法 → INSUFFICIENT；
    - 比较键不一致 → NOT_COMPARABLE；
    - 键一致：值相对误差 <= 容差 → MATCH，否则 CONFLICT。
    """
    if not _has_all_keys(left) or not _has_all_keys(right):
        return "INSUFFICIENT"

    lk, rk = _norm(left), _norm(right)
    if lk != rk:
        return "NOT_COMPARABLE"

    try:
        lv, rv = Decimal(left.value), Decimal(right.value)
    except Exception:  # noqa: BLE001 - 非法数值视为不可比较
        return "INSUFFICIENT"

    if lv == rv:
        return "MATCH"
    if rv == 0:
        return "CONFLICT"

    rel = abs(lv - rv) / abs(rv)
    return "MATCH" if rel <= _TOLERANCE else "CONFLICT"


__all__ = ["FinancialValue", "compare", "Consistency"]