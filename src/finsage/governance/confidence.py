"""§24 Confidence Contract（T703 —— m07）。

置信度由六因素确定性地组合，**绝不使用 LLM self-rating**：
retrieval_quality / evidence_authority / evidence_coverage / calculation_validity /
temporal_validity 五项度量取加权平均，再叠加 verification_result 的门控，并按
V007 数据冲突封顶。阈值分档为规格 §24 初始值（后续由 FinEval 校准，不擅自改）：

    HIGH   >= 0.85
    MEDIUM 0.65 - <0.85
    LOW    0.45 - <0.65
    ABSTAIN < 0.45
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConfidenceBucket = Literal["HIGH", "MEDIUM", "LOW", "ABSTAIN"]

# 各项度量 0..1；规格未给权重，取等权（0.2，合计 1.0），入 FinEval 后方可调整。
_QUALITY_KEYS: tuple[str, ...] = (
    "retrieval_quality",
    "evidence_authority",
    "evidence_coverage",
    "calculation_validity",
    "temporal_validity",
)
_QUALITY_WEIGHT = 0.2

# 阈值（§24 初始值 —— FROZEN）。
_THRESHOLD_HIGH = 0.85
_THRESHOLD_MEDIUM = 0.65
_THRESHOLD_LOW = 0.45

# 数据冲突时上限（MEDIUM 档），阻断 HIGH（V007）。
_CONFLICT_CAP = 0.80
# verification 门控：FAIL 归零 / ABSTAIN 归入 ABSTAIN 档 / PASS 放行。
_VERIFY_FAIL = 0.0
_VERIFY_ABSTAIN = 0.30


@dataclass(frozen=True)
class ConfidenceScore:
    """组合置信度结果（§24）。"""

    score: float
    bucket: ConfidenceBucket
    # 度量过的因素分解（可审计）。
    factors: dict[str, float] = field(default_factory=dict)


def _bucket(score: float) -> ConfidenceBucket:
    if score >= _THRESHOLD_HIGH:
        return "HIGH"
    if score >= _THRESHOLD_MEDIUM:
        return "MEDIUM"
    if score >= _THRESHOLD_LOW:
        return "LOW"
    return "ABSTAIN"


def compute_confidence(
    *,
    retrieval_quality: float | None = None,
    evidence_authority: float | None = None,
    evidence_coverage: float | None = None,
    calculation_validity: float | None = None,
    temporal_validity: float | None = None,
    verification_status: str | None = None,
    data_conflict: bool = False,
) -> ConfidenceScore:
    """确定性组合置信度。

    参数：五项质量度量（0..1，缺省按 0 计，不猜不能确证的证据质量）；
    ``verification_status`` 取 "PASS" / "FAIL" / "ABSTAIN"；``data_conflict``
    表示命中 V007 数据冲突（封顶阻断 HIGH）。
    """
    factors: dict[str, float] = {}
    quality_sum = 0.0
    for key in _QUALITY_KEYS:
        value = locals()[key]
        value = max(0.0, min(1.0, float(value))) if value is not None else 0.0
        factors[key] = value
        quality_sum += value * _QUALITY_WEIGHT

    # verification 门控。
    verify_factor = 1.0
    if verification_status == "FAIL":
        verify_factor = _VERIFY_FAIL
    elif verification_status == "ABSTAIN":
        verify_factor = _VERIFY_ABSTAIN
    factors["verification_status"] = verify_factor

    score = quality_sum * verify_factor

    # V007：数据冲突阻断 HIGH。
    if data_conflict:
        score = min(score, _CONFLICT_CAP)
        factors["data_conflict"] = _CONFLICT_CAP

    score = round(min(1.0, max(0.0, score)), 4)
    return ConfidenceScore(score=score, bucket=_bucket(score), factors=factors)


__all__ = ["ConfidenceScore", "ConfidenceBucket", "compute_confidence"]