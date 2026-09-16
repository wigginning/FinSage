"""SQLAlchemy 模型包：汇总导出全部 19 张表模型（规格 §5.3–5.21）。

导入本模块即可使全量表注册到 Base.metadata，供 alembic autogenerate 与集成测试使用。
"""

from finsage.persistence.models.auth import Session, Tenant, User, UserTenant
from finsage.persistence.models.chat import Message
from finsage.persistence.models.evaluation import EvaluationCase, EvaluationDataset, EvaluationRun
from finsage.persistence.models.governance import AuditEvent, ProviderConfig, ProviderHealth
from finsage.persistence.models.rag import (
    Calculation,
    Claim,
    ClaimEvidence,
    Document,
    DocumentChunk,
    Evidence,
)
from finsage.persistence.models.research import ResearchRun, ResearchTask

__all__ = [
    "AuditEvent",
    "Calculation",
    "Claim",
    "ClaimEvidence",
    "Document",
    "DocumentChunk",
    "EvaluationCase",
    "EvaluationDataset",
    "EvaluationRun",
    "Evidence",
    "Message",
    "ProviderConfig",
    "ProviderHealth",
    "ResearchRun",
    "ResearchTask",
    "Session",
    "Tenant",
    "User",
    "UserTenant",
]
