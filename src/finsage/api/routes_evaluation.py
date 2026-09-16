"""FinEval 评估 API（ADR-0022）。

异步化：POST 仅入队（复用 ``TaskManager``，``kind="evaluation"``）并立即返回 ``task_id``；
真实执行在后台推进，进度经既有 ``/api/v1/tasks/{task_id}/stream`` SSE 观察（不新增流端点）。

权限（ADR-0019 §1/§3）：提交要求 ``member``、读取要求 ``viewer``；提交端点挂限流
（一次运行是 100 条用例的批量执行，属重端点）。

隔离（ADR-0022 §2）：运行归属发起租户，读取按 ``TaskHandle.tenant_id`` 做 IDOR 归属校验。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from finsage.api.auth import require_auth, require_role, resolve_principal
from finsage.api.context import Principal
from finsage.api.evaluation_service import EVALUATION_KIND, build_spec, run_evaluation
from finsage.api.ratelimit import require_rate_limit
from finsage.api.schemas import (
    EvaluationListResponse,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationRunResponse,
)
from finsage.exceptions import ErrorCode, raise_for_code
from finsage.observability.trace import new_trace_id

router = APIRouter(
    prefix="/api/v1/evaluations",
    tags=["evaluation"],
    dependencies=[Depends(require_auth)],
)


def _deps(request: Request) -> Any:
    """取应用运行态容器（见 app.Deps）。"""
    return request.app.state.deps


def _principal(request: Request) -> Principal:
    """解析当前请求身份（优先复用 request.state，未解析则重算）。"""
    principal: Principal | None = getattr(request.state, "principal", None)
    return principal if principal is not None else resolve_principal(request)


def _trace_id_from(request: Request) -> str:
    return request.headers.get("X-Trace-Id") or new_trace_id()


def _assert_tenant_access(request: Request, resource_tenant: str | None) -> None:
    """IDOR 归属校验（与 routes.py 同策略）：跨租户读取一律 FIN-1003。"""
    request_tenant = _principal(request).tenant_id
    if not request_tenant or not resource_tenant:
        return
    if request_tenant != resource_tenant:
        raise_for_code(ErrorCode.FORBIDDEN, "evaluation run does not belong to tenant")


def _to_response(handle: Any) -> EvaluationRunResponse:
    """把任务句柄折成响应体；``result`` 中的报告字段仅在完成后存在。"""
    result: dict[str, Any] = handle.result if isinstance(handle.result, dict) else {}
    return EvaluationRunResponse(
        task_id=handle.task_id,
        status=handle.status,
        progress=handle.progress,
        trace_id=handle.trace_id,
        created_at=handle.created_at,
        error_code=handle.error_code,
        duration_sec=handle.duration_seconds(),
        run_id=result.get("run_id"),
        dataset_name=result.get("dataset_name"),
        dataset_version=result.get("dataset_version"),
        case_count=result.get("case_count"),
        evaluated_count=result.get("evaluated_count"),
        git_commit=result.get("git_commit"),
        executor=result.get("executor"),
        persisted=result.get("persisted"),
        metrics=result.get("metrics"),
    )


@router.post(
    "",
    response_model=EvaluationResponse,
    summary="提交评估运行（异步）",
    dependencies=[Depends(require_role("member")), Depends(require_rate_limit())],
)
async def create_evaluation(req: EvaluationRequest, request: Request) -> EvaluationResponse:
    """入队一次 benchmark 运行并返回 ``task_id``（真实执行在后台）。

    数据集非法（未知 task_type / 过滤后为空）在**提交时**即抛 ``FIN-1001``，
    不制造一个必然失败的后台任务。
    """
    deps = _deps(request)
    trace_id = _trace_id_from(request)
    tenant_id = _principal(request).tenant_id or ""
    spec = build_spec(task_types=req.task_types, limit_per_type=req.limit_per_type)

    handle = await deps.task_manager.submit(
        EVALUATION_KIND,
        trace_id=trace_id,
        run=lambda h: run_evaluation(deps, h, spec=spec, tenant_id=tenant_id),
        query=spec.name,
        tenant_id=tenant_id,
    )
    return EvaluationResponse(
        task_id=handle.task_id,
        trace_id=trace_id,
        dataset_name=spec.name,
        dataset_version=spec.version,
        case_count=spec.case_count,
    )


@router.get(
    "",
    response_model=EvaluationListResponse,
    summary="列出评估运行",
    dependencies=[Depends(require_role("viewer"))],
)
async def list_evaluations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> EvaluationListResponse:
    """分页列出本进程内的评估运行（按创建时间倒序，跨租户条目已过滤）。

    仅覆盖当前进程的任务句柄；重启后的历史运行需查 ``evaluation_runs`` 表
    （见 ADR-0022 Consequences）。
    """
    deps = _deps(request)
    request_tenant = _principal(request).tenant_id
    # 先取一页再按租户过滤会导致分页数量不稳，故取回后统一过滤再切片。
    handles = deps.task_manager.list(kind=EVALUATION_KIND, limit=1000, offset=0)
    if request_tenant:
        handles = [h for h in handles if not h.tenant_id or h.tenant_id == request_tenant]
    total = len(handles)
    page = handles[offset : offset + limit]
    return EvaluationListResponse(
        items=[_to_response(h) for h in page], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{task_id}",
    response_model=EvaluationRunResponse,
    summary="查询评估运行状态与指标",
    dependencies=[Depends(require_role("viewer"))],
)
async def get_evaluation(task_id: str, request: Request) -> EvaluationRunResponse:
    """返回运行状态；完成后含 overall / per_type 指标。"""
    deps = _deps(request)
    handle = deps.task_manager.get(task_id)
    if handle is None or handle.kind != EVALUATION_KIND:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND, "evaluation run not found")
    _assert_tenant_access(request, handle.tenant_id)
    return _to_response(handle)


__all__ = ["router"]
