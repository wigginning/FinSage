"""研究域仓储：research_tasks、research_runs、claims、evidence、calculations（规格 §5.10–5.15）。"""

from __future__ import annotations

from finsage.persistence.models.rag import Calculation, Claim, Evidence
from finsage.persistence.models.research import ResearchRun, ResearchTask
from finsage.persistence.repositories.base import FilteredRepository, TenantScopedRepository


class ResearchTaskRepository(TenantScopedRepository):
    """研究任务仓储：注入租户后自动限该租户；白名单筛选：session_id / type / status / trace_id。"""

    model = ResearchTask
    allow_filters = frozenset({"session_id", "type", "status", "trace_id"})

    def find_by_trace_id(self, trace_id: str):
        """按链路 trace_id 取任务（域对象或 None）。"""
        return self.find_one(trace_id=trace_id)

    def list_for_session(self, session_id: str, *, limit: int = 100, offset: int = 0) -> list:
        """按会话取任务（域对象列表）。"""
        return self.find_many(session_id=session_id, limit=limit, offset=offset)


class ResearchRunRepository(FilteredRepository):
    """研究运行记录仓储。白名单筛选：research_task_id / workflow_name / status。"""

    model = ResearchRun
    allow_filters = frozenset({"research_task_id", "workflow_name", "status"})

    def list_for_task(self, research_task_id: str, *, limit: int = 50, offset: int = 0) -> list:
        """按任务取运行记录（域对象列表）。"""
        return self.find_many(research_task_id=research_task_id, limit=limit, offset=offset)


class ClaimRepository(FilteredRepository):
    """论断仓储。白名单筛选：research_run_id / claim_type / verified。"""

    model = Claim
    allow_filters = frozenset({"research_run_id", "claim_type", "verified"})

    def list_for_run(self, research_run_id: str, *, limit: int = 200, offset: int = 0) -> list:
        """按研究运行取论断（域对象列表）。"""
        return self.find_many(research_run_id=research_run_id, limit=limit, offset=offset)


class EvidenceRepository(TenantScopedRepository):
    """证据仓储：注入租户后自动限该租户；白名单筛选：document_id / chunk_id / provider。"""

    model = Evidence
    allow_filters = frozenset({"document_id", "chunk_id", "provider"})

    def list_for_document(self, document_id: str, *, limit: int = 200, offset: int = 0) -> list:
        """按来源文档取证据（域对象列表）。"""
        return self.find_many(document_id=document_id, limit=limit, offset=offset)


class CalculationRepository(FilteredRepository):
    """计算记录仓储。白名单筛选：research_run_id / period。"""

    model = Calculation
    allow_filters = frozenset({"research_run_id", "period"})

    def list_for_run(self, research_run_id: str, *, limit: int = 200, offset: int = 0) -> list:
        """按研究运行取计算记录（域对象列表）。"""
        return self.find_many(research_run_id=research_run_id, limit=limit, offset=offset)


__all__ = [
    "ResearchTaskRepository",
    "ResearchRunRepository",
    "ClaimRepository",
    "EvidenceRepository",
    "CalculationRepository",
]
