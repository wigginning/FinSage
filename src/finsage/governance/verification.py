"""确定性 Verification（§23 V001–V010 —— m06 内联落地）。

从 Evidence / Calculation / 政策状态推导校验结论，绝不调用 LLM 自评（§24）。
规则：
V001 numeric claim 必须有 Calculation 或 Evidence（含：Calculation 引用必须真实存在，
     悬空 calculation_id 等价无 Calculation，不得因"填了个 id"就放行）；
V002 外部事实必须有 Evidence；
V003 引用必须能解析到有效证据；
V004 期间必须匹配请求期间；
V007 数据冲突阻断高置信（深度检测由 m07/Provider conflict 提供）；
V008 缺证据 -> ABSTAIN；
V009 政策拦截 -> 不产出答案；
V010 校验失败 -> 无最终答案（由节点逻辑落地）。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import VerificationResult

# 可能成为数值型 / 事实型论断的 claim_type。
_NUMERIC_TYPES = frozenset({"numeric", "comparison"})
_FACT_TYPES = frozenset({"fact"})


def verify(
    *,
    claims: Sequence[Any],
    evidences: Sequence[Any],
    calculations: Sequence[Any],
    policy_status: str | None = None,
    expected_period: str | None = None,
    expected_currency: str | None = None,
    expected_unit: str | None = None,
    data_conflicts: Sequence[str] = (),
) -> VerificationResult:
    """确定性校验；命中任一 FAIL 规则即 FAIL，缺证据返回 ABSTAIN，否则 PASS。

    规则覆盖 §23 V001–V010：V005（币种一致或显式转换）、V006（单位一致或显式转换）、
    V007（数据冲突阻断高置信）由调用方把币种/单位口径与冲突信号传入。
    """
    failed_rules: list[str] = []
    reasons: list[str] = []

    # V009：政策拦截 -> 不产出答案。
    if policy_status == "block":
        return VerificationResult(
            status="FAIL", failed_rules=["V009"], reasons=["policy_blocked"]
        )

    evidence_ids = {getattr(e, "id", f"ev:{i}") for i, e in enumerate(evidences)}
    # Calculation 引用集合：用于识别悬空 calculation_id（伪造引用不得通过校验）。
    calculation_ids = {
        cid for c in calculations if (cid := getattr(c, "id", None)) is not None
    }

    for i, claim in enumerate(claims):
        c_type = getattr(claim, "claim_type", "fact")
        c_evidence = list(getattr(claim, "evidence_ids", []) or [])
        c_calc = getattr(claim, "calculation_id", None)

        # V003：引用必须能解析到有效证据。
        unresolved = [eid for eid in c_evidence if eid not in evidence_ids]
        if unresolved:
            failed_rules.append("V003")
            reasons.append(f"claim[{i}] unresolved_citation:{unresolved}")
            continue
        # V001：Calculation 引用必须真实存在（悬空引用 == 无 Calculation）。
        if c_calc is not None and c_calc not in calculation_ids:
            failed_rules.append("V001")
            reasons.append(f"claim[{i}] dangling_calculation:{c_calc}")
            continue
        # V001：数值型论断必须有证据或 Calculation。
        if c_type in _NUMERIC_TYPES and not c_evidence and c_calc is None:
            failed_rules.append("V001")
            reasons.append(f"claim[{i}] numeric_without_evidence_or_calc")
            continue
        # V002：外部事实必须有证据。
        if c_type in _FACT_TYPES and not c_evidence:
            failed_rules.append("V002")
            reasons.append(f"claim[{i}] fact_without_evidence")

    # V004：期间须匹配请求期间。
    if expected_period and any(
        getattr(c, "period", None) and c.period != expected_period
        for c in calculations
    ):
        failed_rules.append("V004")
        reasons.append(f"period_mismatch:{expected_period}")

    # V005：币种须一致或显式转换。
    if expected_currency and any(
        (cu := getattr(c, "output_currency", None)) is not None and cu != expected_currency
        for c in calculations
    ):
        failed_rules.append("V005")
        reasons.append(f"currency_mismatch:{expected_currency}")

    # V006：单位须一致或显式转换。
    if expected_unit and any(
        (u := getattr(c, "output_unit", None)) is not None and u != expected_unit
        for c in calculations
    ):
        failed_rules.append("V006")
        reasons.append(f"unit_mismatch:{expected_unit}")

    # V007：数据冲突阻断高置信（信号由 Provider conflict（m03）比对产出）。
    if data_conflicts:
        failed_rules.append("V007")
        reasons.append(f"data_conflict:{','.join(map(str, data_conflicts))}")

    if failed_rules:
        return VerificationResult(status="FAIL", failed_rules=failed_rules, reasons=reasons)

    # V008：缺证据 -> ABSTAIN（含"零检索零计算零论断"的完全无支撑场景）。
    if not claims and not evidences and not calculations:
        return VerificationResult(
            status="ABSTAIN", failed_rules=["V008"], reasons=["missing_evidence"]
        )

    # V008：有论断但无一绑定证据且无 Calculation 兜底 -> ABSTAIN。
    has_evidence_binding = any(getattr(c, "evidence_ids", None) for c in claims)
    if claims and not has_evidence_binding and not calculations:
        return VerificationResult(
            status="ABSTAIN", failed_rules=["V008"], reasons=["missing_evidence"]
        )

    return VerificationResult(status="PASS")


__all__ = ["verify"]