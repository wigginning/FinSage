"""Agents 图集合（§17–20）。每图以独立包承载，构建入口统一从 ``build_*`` 获取。"""

from finsage.agents.due_diligence.graph import build_due_diligence
from finsage.agents.financial_health.graph import build_financial_health
from finsage.agents.report.graph import build_report
from finsage.agents.research_qa.graph import build_research_qa

__all__ = [
    "build_research_qa",
    "build_financial_health",
    "build_due_diligence",
    "build_report",
]