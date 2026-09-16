"""基础异常体系（T006）。

将规格 §8.1 的 FIN 错误码（FIN-1001 ~ FIN-6001）映射为可识别的异常类型，
并为每个错误码固定 retryable 标志（详见 §8.1 Error Codes 表的 Retry 列）。

规则：
- 业务代码不得以裸 dict 传播错误；统一抛受检的 FinSageError 子类；
- 禁止将 Python exception message 直接暴露给 API 客户端（§8 说明）——
  对外只暴露 HTTP status + FIN 错误码 + 面向用户的稳定 message；
- retryable 信息供上层（Provider Failover / Workflow）决策重试。
"""

from __future__ import annotations

from enum import StrEnum
from typing import NoReturn


class ErrorCode(StrEnum):
    """§8.1 Error Codes —— FROZEN。值即 FIN 错误码字符串。"""

    INVALID_REQUEST = "FIN-1001"
    AUTH_REQUIRED = "FIN-1002"
    FORBIDDEN = "FIN-1003"
    RESOURCE_NOT_FOUND = "FIN-1004"
    # ADR-0020 §7：API 层限流。§8.1 的受控扩展——仅新增一个码，不修改/删除既有码，
    # 也不改动任何既有码的 HTTP 状态与 retryable 语义。
    RATE_LIMITED = "FIN-1005"

    DOCUMENT_PARSE_FAILED = "FIN-1101"
    DOCUMENT_TOO_LARGE = "FIN-1102"

    PROVIDER_TIMEOUT = "FIN-2001"
    PROVIDER_UNAVAILABLE = "FIN-2002"
    PROVIDER_RATE_LIMITED = "FIN-2003"
    PROVIDER_BAD_RESPONSE = "FIN-2004"
    PROVIDER_DATA_CONFLICT = "FIN-2101"
    NORMALIZATION_FAILED = "FIN-2102"
    MARKET_DATA_UNAVAILABLE = "FIN-2201"

    RETRIEVAL_FAILED = "FIN-3001"
    RERANK_FAILED = "FIN-3002"
    NO_EVIDENCE = "FIN-3003"
    CALCULATION_FAILED = "FIN-3101"
    INVALID_FINANCIAL_INPUT = "FIN-3102"

    POLICY_BLOCKED = "FIN-4001"
    ABSTAIN_REQUIRED = "FIN-4002"
    VERIFICATION_FAILED = "FIN-4101"

    WORKFLOW_FAILED = "FIN-5001"
    WORKFLOW_TIMEOUT = "FIN-5002"
    WORKFLOW_CANCELLED = "FIN-5003"

    INTERNAL_ERROR = "FIN-6001"


# retryable 标志（§8.1 Retry 列：yes / no / conditional）。
# False 固定为不可重试；True 固定为可重试；conditional 由业务按语义决定。
_RETRY_FLAG: dict[ErrorCode, bool] = {
    ErrorCode.INVALID_REQUEST: False,
    ErrorCode.AUTH_REQUIRED: False,
    ErrorCode.FORBIDDEN: False,
    ErrorCode.RESOURCE_NOT_FOUND: False,
    ErrorCode.RATE_LIMITED: True,  # ADR-0020 §7：窗口过后可重试
    ErrorCode.DOCUMENT_PARSE_FAILED: False,
    ErrorCode.DOCUMENT_TOO_LARGE: False,
    ErrorCode.PROVIDER_TIMEOUT: True,
    ErrorCode.PROVIDER_UNAVAILABLE: True,
    ErrorCode.PROVIDER_RATE_LIMITED: True,
    ErrorCode.PROVIDER_BAD_RESPONSE: True,
    ErrorCode.PROVIDER_DATA_CONFLICT: False,
    ErrorCode.NORMALIZATION_FAILED: False,
    ErrorCode.MARKET_DATA_UNAVAILABLE: True,
    ErrorCode.RETRIEVAL_FAILED: True,
    ErrorCode.RERANK_FAILED: True,
    ErrorCode.NO_EVIDENCE: False,
    ErrorCode.CALCULATION_FAILED: False,
    ErrorCode.INVALID_FINANCIAL_INPUT: False,
    ErrorCode.POLICY_BLOCKED: False,
    ErrorCode.ABSTAIN_REQUIRED: False,
    ErrorCode.VERIFICATION_FAILED: False,
    ErrorCode.WORKFLOW_FAILED: False,  # conditional：默认按非重试处理
    ErrorCode.WORKFLOW_TIMEOUT: True,
    ErrorCode.WORKFLOW_CANCELLED: False,
    ErrorCode.INTERNAL_ERROR: False,
}

# 每种错误码对应的 HTTP 状态码（对外 API 映射，§8 约束）。
_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.RATE_LIMITED: 429,  # ADR-0020 §7
    ErrorCode.DOCUMENT_PARSE_FAILED: 422,
    ErrorCode.DOCUMENT_TOO_LARGE: 413,
    ErrorCode.PROVIDER_TIMEOUT: 503,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.PROVIDER_RATE_LIMITED: 429,
    ErrorCode.PROVIDER_BAD_RESPONSE: 502,
    ErrorCode.PROVIDER_DATA_CONFLICT: 502,
    ErrorCode.NORMALIZATION_FAILED: 502,
    ErrorCode.MARKET_DATA_UNAVAILABLE: 504,
    ErrorCode.RETRIEVAL_FAILED: 500,
    ErrorCode.RERANK_FAILED: 500,
    ErrorCode.NO_EVIDENCE: 200,
    ErrorCode.CALCULATION_FAILED: 500,
    ErrorCode.INVALID_FINANCIAL_INPUT: 422,
    ErrorCode.POLICY_BLOCKED: 403,
    ErrorCode.ABSTAIN_REQUIRED: 400,
    ErrorCode.VERIFICATION_FAILED: 422,
    ErrorCode.WORKFLOW_FAILED: 500,
    ErrorCode.WORKFLOW_TIMEOUT: 504,
    ErrorCode.WORKFLOW_CANCELLED: 409,
    ErrorCode.INTERNAL_ERROR: 500,
}


class FinSageError(Exception):
    """FinSage 错误基类。

    - code：FIN 错误码；
    - retryable：是否可重试（按 §8.1 Retry 列冻结）；
    - 对外消息应面向用户、稳定且不暴露内部细节/密钥。
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str = "", *, retryable: bool | None = None):
        super().__init__(message)
        self.message = message
        # WORKFLOW_FAILED 为 conditional：可由业务显式覆盖 retryable。
        self.retryable = _RETRY_FLAG[self.code] if retryable is None else retryable

    @property
    def http_status(self) -> int:
        """对外 API 映射的 HTTP 状态码。"""
        return _HTTP_STATUS[self.code]

    def __str__(self) -> str:  # pragma: no cover - 便于调试
        return f"[{self.code.value}] {self.message}"


class APIError(FinSageError):
    """请求/鉴权/权限/资源相关错误（FIN-100x）。"""


class RateLimitedError(APIError):
    """API 层限流（FIN-1005，ADR-0020 §7）。

    与 ``ProviderRateLimitedError``（FIN-2003，上游数据源限流）严格区分：本类表示
    **客户端**请求频率超限，属请求侧约束；``retry_after`` 为建议重试间隔（秒），
    由 API 错误处理器写入 ``Retry-After`` 响应头。
    """

    code = ErrorCode.RATE_LIMITED

    def __init__(
        self, message: str = "请求过于频繁，请稍后重试", *, retry_after: int = 0
    ) -> None:
        # message 为位置参数是为了兼容 ``raise_for_code`` 的调用约定
        # （它把 message 作为首个位置参数传入）；对外文案仍由 errors._USER_MSG 统一覆盖。
        super().__init__(message)
        self.retry_after = retry_after


class DocumentError(FinSageError):
    """文档解析/尺寸错误（FIN-11xx）。"""

    code = ErrorCode.DOCUMENT_PARSE_FAILED


class DocumentTooLargeError(DocumentError):
    code = ErrorCode.DOCUMENT_TOO_LARGE


class ProviderError(FinSageError):
    """Provider 层错误（FIN-20xx）。"""

    code = ErrorCode.PROVIDER_UNAVAILABLE


class ProviderTimeoutError(ProviderError):
    """数据源超时（FIN-2001）。"""

    code = ErrorCode.PROVIDER_TIMEOUT


class ProviderRateLimitedError(ProviderError):
    """数据源限流（FIN-2003）。"""

    code = ErrorCode.PROVIDER_RATE_LIMITED


class ProviderBadResponseError(ProviderError):
    """数据源返回异常（FIN-2004）。"""

    code = ErrorCode.PROVIDER_BAD_RESPONSE


class ProviderDataConflictError(ProviderError):
    code = ErrorCode.PROVIDER_DATA_CONFLICT


class NormalizationError(ProviderError):
    code = ErrorCode.NORMALIZATION_FAILED


class MarketDataUnavailableError(ProviderError):
    code = ErrorCode.MARKET_DATA_UNAVAILABLE


class RetrievalError(FinSageError):
    """检索/RAG 错误（FIN-30xx）。"""

    code = ErrorCode.RETRIEVAL_FAILED


class RerankFailedError(RetrievalError):
    """重排失败（FIN-3002）。"""

    code = ErrorCode.RERANK_FAILED


class NoEvidenceError(RetrievalError):
    code = ErrorCode.NO_EVIDENCE


class CalculationError(FinSageError):
    """确定性计算错误（FIN-31xx）。"""

    code = ErrorCode.CALCULATION_FAILED


class GovernanceError(FinSageError):
    """政策/放弃/校验错误（FIN-40xx）。"""

    code = ErrorCode.POLICY_BLOCKED


class WorkflowError(FinSageError):
    """Workflow 错误（FIN-50xx）。"""

    code = ErrorCode.WORKFLOW_FAILED


class InternalError(FinSageError):
    """未归类内部错误（FIN-6001）。"""

    code = ErrorCode.INTERNAL_ERROR


def raise_for_code(code: ErrorCode, message: str = "") -> NoReturn:
    """按错误码抛对应的默认异常类型；未覆盖的落在 APIError 并携带该错误码。

    标注 ``NoReturn``（而非 ``None``）：本函数**必定**抛异常，标注准确后调用点
    才能被类型检查器正确收窄（如 ``if x is None: raise_for_code(...)`` 之后 ``x``
    不再被视为可能为 None）。
    """
    exc = _MAP.get(code, APIError)(message or f"{code.value} {code.name}")
    exc.code = code  # 显式携带请求错误码，retryable/http_status 依此定型
    raise exc


# 错误码 -> 默认异常类型（具体子类优先）。
_MAP: dict[ErrorCode, type[FinSageError]] = {
    ErrorCode.RATE_LIMITED: RateLimitedError,  # ADR-0020 §7
    ErrorCode.DOCUMENT_TOO_LARGE: DocumentTooLargeError,
    ErrorCode.PROVIDER_TIMEOUT: ProviderTimeoutError,
    ErrorCode.PROVIDER_RATE_LIMITED: ProviderRateLimitedError,
    ErrorCode.PROVIDER_BAD_RESPONSE: ProviderBadResponseError,
    ErrorCode.PROVIDER_DATA_CONFLICT: ProviderDataConflictError,
    ErrorCode.NORMALIZATION_FAILED: NormalizationError,
    ErrorCode.MARKET_DATA_UNAVAILABLE: MarketDataUnavailableError,
    ErrorCode.NO_EVIDENCE: NoEvidenceError,
    ErrorCode.CALCULATION_FAILED: CalculationError,
    ErrorCode.INVALID_FINANCIAL_INPUT: CalculationError,
    ErrorCode.POLICY_BLOCKED: GovernanceError,
    ErrorCode.ABSTAIN_REQUIRED: GovernanceError,
    ErrorCode.VERIFICATION_FAILED: GovernanceError,
    ErrorCode.WORKFLOW_FAILED: WorkflowError,
    ErrorCode.WORKFLOW_TIMEOUT: WorkflowError,
    ErrorCode.WORKFLOW_CANCELLED: WorkflowError,
}
