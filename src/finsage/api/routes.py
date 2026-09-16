"""API 路由（m08，T802–T808，§7）。

所有端点经 ``require_auth`` 鉴权 + 统一 §8 错误契约。任务式端点（chat/research）
仅入队并返回 accepted，真实验证/检索/计算在后台 runner 中推进并产 SSE 事件。

权限（ADR-0019 §1/§3）：读端点要求 ``viewer``、写端点要求 ``member``。静态 token /
匿名请求按 member 级（ADR-0019 §2），故既有部署行为不变；携带真实 viewer 令牌的
请求才被写端点拒绝。

限流（ADR-0020 §4）：仅重端点 ``/chat``、``/research``、``/companies`` 接线，且只在
提交时限流（SSE 流过程不二次限）。Redis 不可用时默认 fail-open。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from finsage.api.auth import require_auth, require_role, resolve_principal
from finsage.api.context import Principal
from finsage.api.ratelimit import require_rate_limit
from finsage.api.schemas import (
    AuditResponse,
    ChatRequest,
    ChatResponse,
    CompanyDetail,
    CompanyListResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentSummary,
    ResearchRequest,
    ResearchResponse,
    StatsResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
    TaskSummary,
)
from finsage.exceptions import ErrorCode, raise_for_code
from finsage.observability.trace import new_trace_id, uuid_str

router = APIRouter(prefix="/api/v1", tags=["finsage"], dependencies=[Depends(require_auth)])

_SSE_MEDIA = "text/event-stream"
# 上传流式分块读取块大小（P1 内存 DoS 防护：分块读并实时校验，不整读内存）。
_UPLOAD_CHUNK = 256 * 1024  # 256 KiB
# 列表接口从内存 task_manager 一次取回的上限（供服务端 keyword 过滤/分页正确性）。
_LIST_FETCH_LIMIT = 1000


def _deps(request: Request) -> Any:
    """取应用运行态容器（见 app.Deps）。"""
    return request.app.state.deps


def _trace_id_from(request: Request) -> str:
    """链路 trace_id：优先取请求头，无则新生成。"""
    return request.headers.get("X-Trace-Id") or new_trace_id()


def _principal(request: Request) -> Principal:
    """解析当前请求身份（优先复用 request.state，未解析则重算）。"""
    principal: Principal | None = getattr(request.state, "principal", None)
    return principal if principal is not None else resolve_principal(request)


def _tenant_provider(request: Request):
    """构造按请求租户作用域的仓储提供器（P0 TenantScopedRepository 接线）。

    供需要持久化查询/写入的端点使用：``_tenant_provider(request).document(session)``
    自动附加 tenant_id 过滤（最小权限）。租户来自请求身份。
    """
    from finsage.persistence.repositories.provider import TenantRepositoryProvider

    return TenantRepositoryProvider(tenant_id=_principal(request).tenant_id or None)


def _assert_tenant_access(request: Request, resource_tenant: str | None) -> None:
    """IDOR 归属校验（P0）：已识别租户的请求只能访问归属同一租户的资源。

    - 请求无租户作用域（开发放行/匿名）→ 放行（保持既有行为）；
    - 资源无租户归属 → 放行（兼容未落租户的历史数据）；
    - 请求租户与资源租户不一致 → FIN-1003 FORBIDDEN（阻断越权读）。
    """
    request_tenant = _principal(request).tenant_id
    if not request_tenant or not resource_tenant:
        return
    if request_tenant != resource_tenant:
        raise_for_code(ErrorCode.FORBIDDEN, "resource does not belong to tenant")


# ---- T802 /chat（§7.1）----


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="发起对话任务",
    dependencies=[Depends(require_role("member")), Depends(require_rate_limit())],
)
async def create_chat(req: ChatRequest, request: Request) -> ChatResponse:
    deps = _deps(request)
    trace_id = _trace_id_from(request)
    session_id = req.session_id or uuid_str()
    handle = await deps.task_manager.submit(
        "chat",
        trace_id=trace_id,
        run=lambda h: deps.runner.run("chat", input_=req, handle=h),
        tenant_id=_principal(request).tenant_id,
    )
    return ChatResponse(
        task_id=handle.task_id, session_id=session_id, trace_id=trace_id, status="accepted"
    )


# ---- T803 /research（§7.2）----


@router.post(
    "/research",
    response_model=ResearchResponse,
    summary="发起研究任务",
    dependencies=[Depends(require_role("member")), Depends(require_rate_limit())],
)
async def create_research(req: ResearchRequest, request: Request) -> ResearchResponse:
    deps = _deps(request)
    trace_id = _trace_id_from(request)
    handle = await deps.task_manager.submit(
        "research",
        trace_id=trace_id,
        run=lambda h: deps.runner.run("research", input_=req, handle=h),
        query=req.query or None,
        company=req.company or None,
        ticker=req.ticker or None,
        market=req.market or None,
        tenant_id=_principal(request).tenant_id,
    )
    return ResearchResponse(task_id=handle.task_id, trace_id=trace_id, status="accepted")


# ---- T804 /tasks/{task_id}（§7.3）----


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    summary="查询任务状态",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_task(task_id: str, request: Request) -> TaskResponse:
    handle = _deps(request).task_manager.get(task_id)
    if handle is None:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, f"task {task_id} not found")
    _assert_tenant_access(request, handle.tenant_id)
    return TaskResponse(
        task_id=handle.task_id,
        status=TaskStatus(handle.status),
        progress=handle.progress,
        trace_id=handle.trace_id,
        result=handle.result,
    )


# ---- T805 /tasks/{task_id}/stream（§7.4/§26.9 SSE）----


@router.get(
    "/tasks/{task_id}/stream",
    summary="SSE 事件流",
    dependencies=[Depends(require_role("viewer"))],
)
async def stream_task(task_id: str, request: Request) -> StreamingResponse:
    deps = _deps(request)
    handle = deps.task_manager.get(task_id)
    if handle is None:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, f"task {task_id} not found")
    _assert_tenant_access(request, handle.tenant_id)

    async def event_source():
        async for ev in deps.task_manager.stream(task_id):
            yield f"data: {ev.model_dump_json()}\n\n"

    return StreamingResponse(event_source(), media_type=_SSE_MEDIA)


# ---- T804b /tasks/{task_id}/abort（§1.3：真实中止，取消后台执行并发 task.aborted）----


@router.post(
    "/tasks/{task_id}/abort",
    response_model=TaskResponse,
    summary="中止任务",
    dependencies=[Depends(require_role("member"))],
)
async def abort_task(task_id: str, request: Request) -> TaskResponse:
    existing = _deps(request).task_manager.get(task_id)
    if existing is None:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, f"task {task_id} not found")
    _assert_tenant_access(request, existing.tenant_id)
    handle = await _deps(request).task_manager.abort(task_id)
    return TaskResponse(
        task_id=handle.task_id,
        status=TaskStatus(handle.status),
        progress=handle.progress,
        trace_id=handle.trace_id,
        result=handle.result,
    )


# ---- T806 /documents（§7.5 multipart）----


@router.post(
    "/documents",
    response_model=DocumentResponse,
    summary="上传研究文档",
    dependencies=[Depends(require_role("member"))],
)
async def upload_document(
    request: Request, file: UploadFile = File(...)  # noqa: B008
) -> DocumentResponse:
    # P1 内存 DoS：流式分块读取并实时校验大小上限，而非先整读进内存再判（§2.6）。
    max_bytes = _deps(request).files.max_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise_for_code(ErrorCode.DOCUMENT_TOO_LARGE, "uploaded document exceeds size limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    # P1 异步化：MySQL 仓储为同步 SQLAlchemy I/O，放入线程池避免阻塞事件循环。
    document_id = await asyncio.to_thread(
        _deps(request).files.register,
        filename=file.filename or "unnamed",
        size=total,
        content=content,
        tenant_id=_principal(request).tenant_id,
    )
    return DocumentResponse(document_id=document_id, status="accepted")


# ---- T807 /evidence/{evidence_id}（§7.6）----


@router.get(
    "/evidence/{evidence_id}",
    summary="读取完整 Evidence",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_evidence(evidence_id: str, request: Request) -> dict[str, Any]:
    evidence = _deps(request).evidence.get(evidence_id)
    if evidence is None:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, f"evidence {evidence_id} not found")
    _assert_tenant_access(request, _deps(request).evidence.owner_tenant(evidence_id))
    return evidence.to_dict() if hasattr(evidence, "to_dict") else dict(evidence)


# ---- T808 /audit/{trace_id}（§7.7）----


@router.get(
    "/audit/{trace_id}",
    response_model=AuditResponse,
    summary="读取审计链路",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_audit(trace_id: str, request: Request) -> AuditResponse:
    events = await asyncio.to_thread(_deps(request).audit.get, trace_id)
    _assert_tenant_access(request, _deps(request).audit.owner_tenant(trace_id))
    return AuditResponse(trace_id=trace_id, events=list(events))


# ---- 列表/读接口扩展（前端 m10 占位页面所需）----


@router.get(
    "/tasks",
    response_model=TaskListResponse,
    summary="列出任务",
    dependencies=[Depends(require_role("viewer"))],
)
async def list_tasks(
    request: Request,
    status: str | None = None,
    kind: str | None = None,
    keyword: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TaskListResponse:
    deps = _deps(request)
    # P2：分页/筛选改为服务端正确执行 —— 先按 status/kind/租户筛选到全量，
    # 再在内存中做 keyword 过滤与分页，避免"只搜前 200 条"（审计 §2.6）。
    handles = deps.task_manager.list(status=status, kind=kind, limit=_LIST_FETCH_LIMIT, offset=0)
    # P0 租户隔离：已识别租户的请求只见本租户任务。
    req_tenant = _principal(request).tenant_id
    if req_tenant:
        handles = [h for h in handles if h.tenant_id == req_tenant]
    if keyword:
        kw = keyword.strip().lower()
        handles = [
            h
            for h in handles
            if kw in (h.query or "").lower()
            or kw in (h.company or "").lower()
            or kw in (h.ticker or "").lower()
        ]
    total = len(handles)
    page = handles[offset : offset + max(0, limit)]
    return TaskListResponse(
        items=[
            TaskSummary(
                task_id=h.task_id,
                kind=h.kind,
                status=TaskStatus(h.status),
                progress=h.progress,
                trace_id=h.trace_id,
                created_at=h.created_at,
                error_code=h.error_code,
                query=h.query,
                company=h.company,
                ticker=h.ticker,
                duration_sec=h.duration_seconds(),
            )
            for h in page
        ],
        total=total,
    )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="列出文档",
    dependencies=[Depends(require_role("viewer"))],
)
async def list_documents(
    request: Request,
    keyword: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DocumentListResponse:
    deps = _deps(request)
    items = await asyncio.to_thread(deps.files.list, limit=limit, offset=offset)
    # P0 租户隔离：已识别租户的请求只见本租户文档。
    req_tenant = _principal(request).tenant_id
    if req_tenant:
        items = [d for d in items if d.get("tenant_id") == req_tenant]
    if keyword:
        kw = keyword.strip().lower()
        items = [d for d in items if kw in d["filename"].lower()]
    return DocumentListResponse(
        items=[
            DocumentSummary(
                document_id=d["document_id"],
                filename=d["filename"],
                size=d["size"],
                created_at=d.get("created_at", ""),
                chunk_count=d.get("chunk_count", 0),
                status=d.get("status", "ingested"),
                citation_count=d.get("citation_count", 0),
            )
            for d in items
        ],
        total=len(items),
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentSummary,
    summary="读取文档元数据",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_document(document_id: str, request: Request) -> DocumentSummary:
    doc = await asyncio.to_thread(_deps(request).files.get, document_id)
    if doc is None:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, f"document {document_id} not found")
    _assert_tenant_access(request, doc.get("tenant_id"))
    return DocumentSummary(
        document_id=doc["document_id"],
        filename=doc["filename"],
        size=doc["size"],
        created_at=doc.get("created_at", ""),
        chunk_count=doc.get("chunk_count", 0),
        status=doc.get("status", "ingested"),
        citation_count=doc.get("citation_count", 0),
    )


# ---- Companies API（ADR-0006，Proposed）----


@router.get(
    "/companies",
    response_model=CompanyListResponse,
    summary="列出公司",
    dependencies=[Depends(require_role("viewer")), Depends(require_rate_limit())],
)
async def list_companies(
    request: Request,
    market: str | None = None,
    keyword: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    enrich: bool = True,
) -> CompanyListResponse:
    return await _deps(request).companies.list(
        market=market, keyword=keyword, limit=limit, offset=offset, enrich=enrich
    )


@router.get(
    "/companies/{ticker}",
    response_model=CompanyDetail,
    summary="读取公司详情",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_company(
    ticker: str, request: Request, market: str | None = None
) -> CompanyDetail:
    detail = await _deps(request).companies.get(ticker, market=market)
    if detail is None:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, f"company {ticker} not found")
    return detail


# ---- 聚合统计（首页 StatCard 数据源）----


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="聚合统计",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_stats(request: Request) -> StatsResponse:
    deps = _deps(request)
    # 只取计数，不做 Provider 增强（§3.1：原 companies.list(limit=1) 会做
    # akshare→baostock failover 增强，~20s 纯浪费）。
    return StatsResponse(
        companies_count=deps.companies.count(),
        tasks_count=deps.task_manager.count(),
        evidence_count=deps.evidence.count(),
        calculations_count=0,
    )


__all__ = ["router"]