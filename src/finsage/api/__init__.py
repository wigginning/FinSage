"""API 层（m08 —— REST + SSE，§7 API Contract / §8 Error Contract / §26.9 SSE）。

顶层入口：``create_app`` 构建 FastAPI 应用；``Deps`` 为可注入的运行态依赖容器
（任务管理/工作流 runner/文档/证据/审计），测试与生产装配均可替换实现。
"""
from __future__ import annotations

from finsage.api.app import (
    AuditStore,
    Deps,
    EvidenceStore,
    FileStore,
    WorkflowRunner,
    build_deps,
    create_app,
)
from finsage.api.routes import router

__all__ = [
    "create_app",
    "router",
    "Deps",
    "build_deps",
    "WorkflowRunner",
    "FileStore",
    "EvidenceStore",
    "AuditStore",
]