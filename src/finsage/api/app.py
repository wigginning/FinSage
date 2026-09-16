"""API 应用装配（m08，§7/§8）。

``Deps``：运行态依赖容器，统一放在 ``app.state.deps``，便于测试注入替身与替换为
DB 支撑实现：
- ``task_manager``：内存任务管理（T804/T805）；
- ``runner``：工作流执行器（生产注入 m06 图，默认 dev_runner 作 smoke 替身，
  忠实产出 §26.9 事件序列 + 记录审计，不伪装真实检索/计算）；
- ``files`` / ``evidence`` / ``audit``：内存存储容器（生产可替换为 m01 仓储）。

鉴权经 ``require_auth`` 依赖，错误经 §8 处理器统一定型；Trace middleware 把
``X-Trace-Id`` 传播到链路上下文。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from finsage.api.errors import register_exception_handlers
from finsage.api.routes import router
from finsage.api.routes_auth import router as auth_router
from finsage.api.routes_evaluation import router as evaluation_router
from finsage.api.tasks import WORKFLOW_STAGE, TaskHandle, TaskManager
from finsage.observability.trace import (
    new_trace_id,
    restore,
    set_trace_id,
    trace_token,
    uuid_str,
)
from finsage.providers.finance._executor import install_bounded_default_executor
from finsage.settings import Settings, get_settings

_APP_TITLE = "FinSage API"
_APP_VERSION = "0.1.0"
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB（§7.5 文档大小上限，可经 FileStore 覆盖）


def _iso_now() -> str:
    """当前 ISO-8601 UTC 时间（用于文档上传时间等）。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class WorkflowRunner(Protocol):
    """工作流执行器契约：按任务类型推进并产出 §26.9 事件。"""

    async def run(self, kind: str, *, input_: Any, handle: TaskHandle) -> None: ...


# 存储契约 Protocol：内存实现（下方 dataclass）与 MySQL 实现（mysql_stores）均须满足，
# 因此 _Stores / Deps / runner 统一按契约引用，而非绑定具体 dataclass，
# 实现规格要求的“生产可替换为 m01 仓储”（§7/§8）。
class FileStoreProto(Protocol):
    """文档上传存储契约（接口对齐内存 ``FileStore``）。"""

    def register(
        self, *, filename: str, size: int, content: bytes, tenant_id: str = ...
    ) -> str: ...

    def get(self, document_id: str) -> dict[str, Any] | None: ...

    def list(self, *, limit: int = ..., offset: int = ...) -> list[dict[str, Any]]: ...

    def count(self) -> int: ...


class AuditStoreProto(Protocol):
    """审计链路存储契约（接口对齐内存 ``AuditStore``）。"""

    def add(
        self, trace_id: str, event: dict[str, Any], *, tenant_id: str = ...
    ) -> None: ...

    def get(self, trace_id: str) -> list[dict[str, Any]]: ...

    def owner_tenant(self, trace_id: str) -> str: ...


@dataclass
class FileStore:
    """文档上传内存容器（T806）。生产可替换为 m01 文档仓储。"""

    max_bytes: int = _DEFAULT_MAX_BYTES
    _items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register(
        self, *, filename: str, size: int, content: bytes, tenant_id: str = ""
    ) -> str:
        document_id = uuid_str()
        self._items[document_id] = {
            "document_id": document_id,
            "filename": filename,
            "size": size,
            "created_at": _iso_now(),
            # P0 权限：记录文档归属租户（IDOR 校验用）。
            "tenant_id": tenant_id,
            # §2.7 溯源统计：内存态默认已入库、分块/引用数待真实索引后回填。
            "chunk_count": 0,
            "status": "ingested",
            "citation_count": 0,
        }
        return document_id

    def get(self, document_id: str) -> dict[str, Any] | None:
        return self._items.get(document_id)

    def list(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """按上传时间倒序分页列出文档元数据（不含内容）。"""
        items = sorted(self._items.values(), key=lambda d: d.get("created_at", ""), reverse=True)
        return items[offset : offset + max(0, limit)]

    def count(self) -> int:
        """文档总数。"""
        return len(self._items)


@dataclass
class EvidenceStore:
    """Evidence 内存容器（T807）。生产可替换为 m01 证据仓储。"""

    _items: dict[str, Any] = field(default_factory=dict)
    _owners: dict[str, str] = field(default_factory=dict)  # evidence_id -> tenant_id

    def add(self, evidence_id: str, obj: Any, *, tenant_id: str = "") -> None:
        self._items[evidence_id] = obj
        if tenant_id:
            self._owners[evidence_id] = tenant_id

    def get(self, evidence_id: str) -> Any | None:
        return self._items.get(evidence_id)

    def owner_tenant(self, evidence_id: str) -> str:
        """取证据归属租户（未记录返回空串）。"""
        return self._owners.get(evidence_id, "")

    def count(self) -> int:
        """证据总数（用于统计接口）。"""
        return len(self._items)


@dataclass
class AuditStore:
    """审计链路内存容器（T808）。生产可替换为 m01 audit_events 仓储。"""

    _items: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _owners: dict[str, str] = field(default_factory=dict)  # trace_id -> tenant_id

    def add(self, trace_id: str, event: dict[str, Any], *, tenant_id: str = "") -> None:
        self._items.setdefault(trace_id, []).append(event)
        if tenant_id:
            self._owners[trace_id] = tenant_id

    def get(self, trace_id: str) -> list[dict[str, Any]]:
        return self._items.get(trace_id, [])

    def owner_tenant(self, trace_id: str) -> str:
        """取审计链路归属租户（未记录返回空串）。"""
        return self._owners.get(trace_id, "")


@dataclass
class _Stores:
    """运行态仓储容器（文件 / 证据 / 审计），按存储契约引用实现。"""

    files: FileStoreProto
    evidence: EvidenceStore
    audit: AuditStoreProto


def build_stores(settings: Settings) -> _Stores:
    """按配置选择内存或 MySQL 持久化仓储。

    - 关闭时（默认 dev/test）：内存 Store（既有行为）；
    - 开启时（``persistence_enabled``，含生产默认）：审计轨迹落 MySQL
      （``MySQLAuditStore``）、文档上传元数据落 MySQL（``MySQLFileStore``，ADR-0007），
      证据暂保留内存（P2-C.2 后续）。需先 ``alembic upgrade head`` 且 ``FIN_DB_URL`` 可达。
    """
    if settings.persistence_enabled:
        from finsage.api.mysql_stores import MySQLAuditStore, MySQLFileStore

        return _Stores(
            files=MySQLFileStore(), evidence=EvidenceStore(), audit=MySQLAuditStore()
        )
    return _Stores(files=FileStore(), evidence=EvidenceStore(), audit=AuditStore())


class DevRunner:
    """**开发/冒烟替身** runner：按 §26.9 事件集产出一组代表性事件并记录审计。

    不执行真实的检索/Provider/计算（AGENTS.md Honesty —— 不伪装生产能力）。
    生产实例应在 m09/m10 装配时注入真实 m06 图执行器（同样实现 WorkflowRunner）。
    """

    def __init__(self, audit: AuditStoreProto) -> None:
        self._audit = audit

    async def run(self, kind: str, *, input_: Any, handle: TaskHandle) -> None:
        handle.emit(WORKFLOW_STAGE, {"name": "parse", "status": "ok"})
        handle.emit("retrieval.completed", {"hits": 3})
        handle.emit("financial_data.completed", {"metrics": 5})
        handle.emit("calculation.completed", {"count": 2})
        await asyncio.to_thread(
            self._audit.add,
            handle.trace_id,
            {"stage": "workflow", "type": kind, "status": "ok"},
            tenant_id=getattr(handle, "tenant_id", None) or "",
        )
        handle.set_progress(0.9)
        await asyncio.to_thread(
            self._audit.add,
            handle.trace_id,
            {"stage": "verification", "status": "ok"},
            tenant_id=getattr(handle, "tenant_id", None) or "",
        )
        # 产出完整 happy-path 事件序列（§26.6 前端状态机要求
        # running→streaming→verifying→completed）：answer.delta 推进 streaming，
        # verification.started 推进 verifying，随后 _execute 发 task.completed 收尾。
        answer_text = "dev-runner stub（真实执行由 m06+m07 装配）"
        handle.emit("answer.delta", {"delta": answer_text})
        handle.emit(
            "answer.completed",
            {
                "answer": answer_text,
                "claims": [],
                "evidences": [],
                "calculations": [],
                "citations": [],
                "confidence": 0,
                "warnings": [],
                "audit_id": "",
            },
        )
        handle.emit("verification.started", {})
        handle.emit("verification.completed", {})
        handle.result = {"kind": kind, "answer": answer_text}


@dataclass
class Deps:
    """API 运行态依赖容器（访问入口：``app.state.deps``）。"""

    settings: Settings
    task_manager: TaskManager
    runner: WorkflowRunner
    files: FileStoreProto
    evidence: EvidenceStore
    audit: AuditStoreProto
    companies: Any = None  # CompanyService（ADR-0006）
    redis: Any = None  # FinRedis（ADR-0020 限流；未装配时限流按降级策略处理）
    # CaseExecutor（ADR-0022 FinEval API）：缺省 DevEvalExecutor（诚实占位，返回 None，
    # 由 evaluator 据实评分）；生产可注入图驱动 executor 做真实端到端评测。
    evaluation_executor: Any = None


def build_deps(*, settings: Settings | None = None, runner: WorkflowRunner | None = None) -> Deps:
    """组装默认依赖。

    ``runner`` 未注入时：
    - 若 ``Settings.enable_real_runner`` 为真，注入真实 m06 图执行器
      （``RealWorkflowRunner``，生产装配点）；
    - 否则使用开发冒烟替身 ``DevRunner``（默认，保持既有行为）。
    装配真实执行器失败则安全回退 ``DevRunner``，保证 API 可用。
    """
    settings = settings or get_settings()
    stores = build_stores(settings)
    task_manager = TaskManager()
    if runner is None and getattr(settings, "enable_real_runner", False):
        from finsage.api.runner_real import build_real_runner

        try:
            runner = build_real_runner(stores.audit, settings=settings)
        except Exception:  # 装配失败退回冒烟替身，避免 API 不可用
            runner = DevRunner(stores.audit)
    from finsage.api.companies import CompanyService
    from finsage.evaluation.executors import build_dev_executor

    companies = CompanyService(task_manager=task_manager, registry=_build_registry_optional())
    return Deps(
        settings=settings,
        task_manager=task_manager,
        runner=runner or DevRunner(stores.audit),
        files=stores.files,
        evidence=stores.evidence,
        audit=stores.audit,
        companies=companies,
        redis=_build_redis_optional(),
        evaluation_executor=build_dev_executor(),
    )


def _build_redis_optional() -> Any | None:
    """装配 Redis 封装（best-effort）；失败返回 None（限流按 ADR-0020 §3 降级）。

    注意 ``Redis.from_url`` 是**惰性连接**，装配阶段通常不会抛错；真正的连接错误在
    首次计数时才抛出，由 ``api.ratelimit`` 的 try/except 兜住并按降级策略处理。
    """
    try:
        from finsage.persistence.redis import get_fin_redis

        return get_fin_redis()
    except Exception:  # noqa: BLE001 —— Redis 不可用不阻塞 API 装配
        return None


def _build_registry_optional() -> Any | None:
    """装配 Provider Registry（best-effort）；失败返回 None（诚实空增强）。"""
    try:
        from finsage.providers.finance import build_registry

        return build_registry()
    except Exception:  # noqa: BLE001 —— Provider 装配失败不阻塞 API
        return None


class _TraceMiddleware(BaseHTTPMiddleware):
    """把请求头 ``X-Trace-Id`` 传播到链路上下文；缺失则新生成。"""

    async def dispatch(self, request: Request, call_next):
        token = trace_token()
        set_trace_id(request.headers.get("X-Trace-Id") or new_trace_id())
        try:
            return await call_next(request)
        finally:
            restore(token)


async def _lifespan(app: FastAPI) -> Any:
    """App 生命周期：启动时为运行中的事件循环安装**有界**默认线程池。

    覆盖进程内所有 ``asyncio.to_thread``（providers / auth / memory / companies），
    防止超时 SDK 调用在默认无界线程池里堆积线程（技术债修复，见
    ``finsage.providers.finance._executor``）。
    """
    loop = asyncio.get_running_loop()
    install_bounded_default_executor(loop)
    yield


def create_app(*, settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    """构建 FastAPI 应用：路由 + §8 错误处理 + 鉴权 + trace + 依赖容器。

    - ``settings``：应用配置（鉴权/调试等）；
    - ``deps``：运行态依赖（默认经 ``build_deps`` 组装，测试可注入替身）。
    """
    settings = settings or get_settings()
    deps = deps or build_deps(settings=settings)
    app = FastAPI(title=_APP_TITLE, version=_APP_VERSION, lifespan=_lifespan)
    app.state.settings = settings
    app.state.deps = deps
    app.include_router(router)
    # 登录路由不套 require_auth（ADR-0019 §4）——登录本身就是获取令牌的手段，
    # 要求先持有令牌会形成死锁；其安全性由凭据校验承担。
    app.include_router(auth_router)
    # FinEval 评估路由（ADR-0022）：独立 router，自带 require_auth + 角色/限流依赖。
    app.include_router(evaluation_router)
    register_exception_handlers(app)
    app.add_middleware(_TraceMiddleware)
    # 前后端分离：允许前端容器/本地开发跨域访问 API（浏览器→API）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


__all__ = [
    "Deps",
    "build_deps",
    "create_app",
    "WorkflowRunner",
    "DevRunner",
    "FileStore",
    "EvidenceStore",
    "AuditStore",
]