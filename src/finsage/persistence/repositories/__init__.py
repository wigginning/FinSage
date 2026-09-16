"""仓储层（T104）：按域提供具体仓储，统一返回 ORM 域对象，禁止跨层裸 dict。

最小权限：带租户表的仓储（TenantScopedRepository）在构造时注入当前租户，
所有查询自动附加 tenant_id 过滤；筛选字段一律受 allow_filters 白名单约束。
"""

from __future__ import annotations

from finsage.persistence.repositories.auth import (
    SessionRepository,
    TenantRepository,
    UserRepository,
    UserTenantRepository,
)
from finsage.persistence.repositories.base import (
    BaseRepository,
    FilteredRepository,
    TenantScopedRepository,
)
from finsage.persistence.repositories.chat import MessageRepository
from finsage.persistence.repositories.evaluation import (
    EvaluationCaseRepository,
    EvaluationDatasetRepository,
    EvaluationRunRepository,
)
from finsage.persistence.repositories.governance import (
    AuditEventRepository,
    ProviderConfigRepository,
    ProviderHealthRepository,
)
from finsage.persistence.repositories.rag import DocumentChunkRepository, DocumentRepository
from finsage.persistence.repositories.research import (
    CalculationRepository,
    ClaimRepository,
    EvidenceRepository,
    ResearchRunRepository,
    ResearchTaskRepository,
)

__all__ = [
    "AuditEventRepository",
    "BaseRepository",
    "CalculationRepository",
    "ClaimRepository",
    "DocumentChunkRepository",
    "DocumentRepository",
    "EvaluationCaseRepository",
    "EvaluationDatasetRepository",
    "EvaluationRunRepository",
    "EvidenceRepository",
    "FilteredRepository",
    "MessageRepository",
    "ProviderConfigRepository",
    "ProviderHealthRepository",
    "ResearchRunRepository",
    "ResearchTaskRepository",
    "SessionRepository",
    "TenantRepository",
    "TenantScopedRepository",
    "UserRepository",
    "UserTenantRepository",
]
