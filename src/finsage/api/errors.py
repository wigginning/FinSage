"""API 错误处理（m08，§8 Error Contract）。

- 将 FinSageError（携带 FIN 错误码 / retryable / http_status）统一转成
  {error:{code,message,retryable,trace_id,details}}；
- 未归类异常 → FIN-6001 INTERNAL_ERROR，**绝不透传 Python exception message**
  （§8：禁止将 Python exception message 直接暴露给 API 客户端）；
- trace_id 取自当前链路上下文；缺失时保障兜底生成并回填。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from finsage.exceptions import ErrorCode, FinSageError
from finsage.observability.trace import get_trace_id

logger = logging.getLogger(__name__)

# 面向用户的稳定 message（不暴露内部细节 / 密钥）。
_USER_MSG: dict[str, str] = {
    ErrorCode.INVALID_REQUEST.value: "请求参数不合法",
    ErrorCode.AUTH_REQUIRED.value: "需要有效的访问令牌",
    ErrorCode.RESOURCE_NOT_FOUND.value: "资源不存在",
    ErrorCode.RATE_LIMITED.value: "请求过于频繁，请稍后重试",  # ADR-0020 §7
    ErrorCode.DOCUMENT_PARSE_FAILED.value: "文档解析失败",
    ErrorCode.DOCUMENT_TOO_LARGE.value: "文档过大",
    ErrorCode.POLICY_BLOCKED.value: "请求被策略拦截",
    ErrorCode.ABSTAIN_REQUIRED.value: "证据不足，无法给出确定性结论",
    ErrorCode.VERIFICATION_FAILED.value: "结论未通过校验",
    ErrorCode.WORKFLOW_FAILED.value: "工作流执行失败",
    ErrorCode.WORKFLOW_TIMEOUT.value: "工作流执行超时",
    ErrorCode.INTERNAL_ERROR.value: "服务内部错误",
}


def _trace_id() -> str:
    """读取当前链路 trace_id；无则兜底返回空串（响应契约要求必填）。"""
    return get_trace_id() or ""


def _error(
    status: int, code: str, retryable: bool, message: str, details: dict | None = None
) -> JSONResponse:
    """组装 §8 error 信封。message 一律用稳定文案，不透传内部异常文本。"""
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "trace_id": _trace_id(),
            "details": details or {},
        }
    }
    return JSONResponse(status_code=status, content=body)


def handle_finsage_error(request: Request, exc: FinSageError) -> JSONResponse:
    """FinSageError → §8 信封（FIN 错误码 + 稳定 message，禁透传）。"""
    code = exc.code.value
    message = _USER_MSG.get(code, f"{code} 请求处理失败")
    response = _error(exc.http_status, code, exc.retryable, message, details={"code": code})
    # ADR-0020 §7：限流（FIN-1005）响应带 Retry-After（剩余窗口秒数）。
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        response.headers["Retry-After"] = str(int(retry_after))
    return response


def handle_validation_error(
    request: Request, exc: RequestValidationError | ValidationError
) -> JSONResponse:
    """入参校验失败 → FIN-1001 INVALID_REQUEST（400）。"""
    if isinstance(exc, RequestValidationError):
        _errors: list[Any] = getattr(exc, "errors", lambda: [])()
    else:
        _errors = exc.errors() or []
    details = {
        "errors": [
            {"loc": list(err.get("loc", [])), "msg": str(err.get("msg", ""))} for err in _errors
        ]
    }
    return _error(
        400,
        ErrorCode.INVALID_REQUEST.value,
        False,
        _USER_MSG[ErrorCode.INVALID_REQUEST.value],
        details,
    )


def handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
    """未归类异常 → FIN-6001 INTERNAL_ERROR（500），不透传内部信息。"""
    logger.warning("unhandled api error: %s", type(exc).__name__, exc_info=exc)
    return _error(
        500,
        ErrorCode.INTERNAL_ERROR.value,
        False,
        _USER_MSG[ErrorCode.INTERNAL_ERROR.value],
    )


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册 §8 错误处理。

    Starlette 的 ``add_exception_handler`` 契约要求处理器签名为
    ``(Request, Exception) -> Response``；这里用薄包装把特化异常收窄回各自强类型
    处理函数（运行时 Starlette 保证传入的就是对应子类），既满足静态类型又保留域逻辑
    的类型安全。
    """

    async def _on_finsage(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, FinSageError)
        return handle_finsage_error(request, exc)

    async def _on_validation(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, (RequestValidationError, ValidationError))
        return handle_validation_error(request, exc)

    app.add_exception_handler(FinSageError, _on_finsage)
    app.add_exception_handler(RequestValidationError, _on_validation)
    app.add_exception_handler(Exception, handle_unhandled)


__all__ = ["register_exception_handlers"]