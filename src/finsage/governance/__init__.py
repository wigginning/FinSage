"""治理域（Policy / Verification / Confidence / Audit —— m07）。

- policy.PolicyGate：§16.5 政策门（确定性规则）。
- verification.verify：§23 V001–V010 确定性校验。
- confidence.compute_confidence：§24 六因素组合置信度（非 LLM self-rating）。
- audit.AuditSink / InMemoryAuditSink / PersistentAuditWriter：§25 审计写入（全字段、无 secret）。
- 域模型（VerificationResult / PolicyVerdict）见 ``governance.models``。
"""
from __future__ import annotations

from .audit import (
    AuditSink,
    InMemoryAuditSink,
    PersistentAuditWriter,
)
from .confidence import ConfidenceBucket, ConfidenceScore, compute_confidence
from .models import PolicyVerdict, VerificationResult
from .policy import PolicyGate
from .verification import verify

__all__ = [
    "PolicyGate",
    "PolicyVerdict",
    "verify",
    "VerificationResult",
    "compute_confidence",
    "ConfidenceScore",
    "ConfidenceBucket",
    "AuditSink",
    "InMemoryAuditSink",
    "PersistentAuditWriter",
]