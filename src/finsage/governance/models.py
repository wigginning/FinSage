"""治理域模型（§23 Verification / Policy —— m06 内联落地，m07 可复用）。

VerificationResult 对应 §23 Verification 产出；PolicyVerdict 对应 §16.5 policy_node
与 §16.13 abstention 的判定载体。均为确定性地步，禁止 LLM 自评（§24）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 校验结论（§23.1）：PASS / FAIL / ABSTAIN。
VerificationStatus = Literal["PASS", "FAIL", "ABSTAIN"]


class VerificationResult(BaseModel):
    """确定性校验结果（§23）。"""

    status: VerificationStatus = "PASS"
    # 命中的校验规则（V001..V010）。
    failed_rules: list[str] = Field(default_factory=list)
    # 每条失败的具体原因（人类可读，用于 audit）。
    reasons: list[str] = Field(default_factory=list)


# policy_node 判定（§16.5）。
PolicyStatus = Literal["allow", "block", "abstain"]


class PolicyVerdict(BaseModel):
    """政策门判定结果（§16.5）。"""

    status: PolicyStatus
    warnings: list[str] = Field(default_factory=list)


__all__ = ["VerificationResult", "VerificationStatus", "PolicyVerdict", "PolicyStatus"]