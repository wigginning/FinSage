"""API 数据契约层（m08，§7 API Contract / §8 Error Contract / §26.9 SSE）。

逐字段对齐规格：
- §7.1–7.7 的 request/response；
- §8 统一 error 信封 {error:{code,message,retryable,trace_id,details}}；
- §26.9 SSE 统一事件信封 {event_id, trace_id, timestamp, type, data}。

禁止在 API 契约里透出 Python exception message（§8），错误只走 FIN 错误码。
"""
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- 输入校验边界（审计 §2.6）----
# query/message 原无长度上限，可直灌 LLM 与检索（成本 + 可用性风险）。
# 4000 字符远高于正常研究问题长度，留足余量。
MAX_QUERY_LENGTH = 4000

# 允许的市场枚举：原为裸 str，非法值会一路透传到 Provider 路由后才失败。
MarketCode = Literal["CN", "US", "HK", "GLOBAL"]

# ---- T802 /chat（§7.1）----


class ChatRequest(BaseModel):
    """POST /api/v1/chat 请求（§7.1）。"""

    session_id: str | None = Field(default=None, description="会话 id；null 表示新建会话")
    message: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH, description="用户消息")
    stream: bool = Field(default=False, description="是否流式返回 SSE")


class ChatResponse(BaseModel):
    """POST /api/v1/chat 响应（§7.1）。"""

    task_id: str = Field(description="任务 id（UUID4）")
    session_id: str = Field(description="会话 id")
    trace_id: str = Field(description="链路 trace_id")
    status: Literal["accepted"] = "accepted"


# ---- T803 /research（§7.2）----


class ResearchOptions(BaseModel):
    """/research 可选项（§7.2 options）。"""

    include_calculation: bool = True
    include_evidence: bool = True
    max_evidence: int = Field(default=10, ge=1, le=100)


class ResearchRequest(BaseModel):
    """POST /api/v1/research 请求（§7.2）。"""

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH, description="研究问题")
    company: str = Field(default="", max_length=200, description="公司名（可空）")
    ticker: str = Field(default="", max_length=32, description="股票代码（可空）")
    market: MarketCode = Field(default="CN", description="市场：CN / US / HK / GLOBAL")
    session_id: str | None = Field(default=None, description="会话 id；null 表示新建会话")
    options: ResearchOptions = Field(default_factory=ResearchOptions)


class ResearchResponse(BaseModel):
    """POST /api/v1/research 响应（§7.2）。"""

    task_id: str = Field(description="任务 id（UUID4）")
    trace_id: str = Field(description="链路 trace_id")
    status: Literal["accepted"] = "accepted"


# ---- T804 /tasks/{task_id}（§7.3）----


class TaskStatus(StrEnum):
    """任务生命周期（§7.3 status 枚举）。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class TaskResponse(BaseModel):
    """GET /api/v1/tasks/{task_id} 响应（§7.3）。"""

    task_id: str
    status: TaskStatus
    progress: float = Field(ge=0, le=1, description="0..1 进度")
    trace_id: str
    result: Any | None = Field(default=None, description="完成后结果；运行中为 null")


class TaskSummary(BaseModel):
    """GET /api/v1/tasks 单项摘要（§7.3 列表视图）。"""

    task_id: str
    kind: str = Field(description="任务类型：chat / research")
    status: TaskStatus
    progress: float = Field(ge=0, le=1, description="0..1 进度")
    trace_id: str
    created_at: str = Field(description="ISO-8601 UTC 创建时间")
    error_code: str | None = Field(default=None, description="失败时的 FIN 错误码；否则 null")
    query: str | None = Field(default=None, description="研究主题（research 有值；chat 为 null）")
    company: str | None = Field(default=None, description="公司名（research 类任务有值）")
    ticker: str | None = Field(default=None, description="股票代码（research 类任务有值）")
    duration_sec: float | None = Field(
        default=None, description="执行耗时（秒）；未完成/未知为 null"
    )


class TaskListResponse(BaseModel):
    """GET /api/v1/tasks 响应：分页任务列表。"""

    items: list[TaskSummary] = Field(default_factory=list)
    total: int = Field(description="筛选后的任务总数（用于分页）")


# ---- T806 /documents（§7.5）----


class DocumentResponse(BaseModel):
    """POST /api/v1/documents 响应（§7.5）。"""

    document_id: str
    status: Literal["accepted"] = "accepted"


class DocumentSummary(BaseModel):
    """GET /api/v1/documents 单项摘要（§7.5 列表/详情视图）。"""

    document_id: str
    filename: str
    size: int = Field(description="字节数")
    created_at: str = Field(default="", description="ISO-8601 UTC 上传时间")
    chunk_count: int = Field(default=0, description="分块数（§2.7 溯源统计）")
    status: str = Field(default="ingested", description="文档状态：ingested/processing/failed")
    citation_count: int = Field(default=0, description="被引用次数（§2.7 溯源统计）")


class DocumentListResponse(BaseModel):
    """GET /api/v1/documents 响应：分页文档列表。"""

    items: list[DocumentSummary] = Field(default_factory=list)
    total: int = Field(description="文档总数（用于分页）")


# ---- Companies API（ADR-0006，Proposed）----


class CompanySummary(BaseModel):
    """GET /api/v1/companies 单项摘要（ADR-0006）。

    数据装配：公司档案/行情经 Provider Registry（AGENTS.md §4），研究次数/最近研究
    聚合自 TaskManager；未就绪字段诚实为 null，绝不返回演示占位数字。
    """

    ticker: str = Field(description="稳定标识（如 300750 / AAPL / 0700）")
    name: str = Field(description="公司名")
    market: str = Field(description="市场：CN / US / HK / GLOBAL")
    industry: str | None = Field(default=None, description="行业（Provider 提供时）")
    currency: str | None = Field(default=None, description="币种")
    price: Decimal | None = Field(default=None, description="现价（Quote，Provider 提供时）")
    change_pct: Decimal | None = Field(default=None, description="涨跌幅（确定性计算）")
    research_count: int = Field(default=0, description="被研究次数（聚合自任务）")
    last_researched_at: str | None = Field(default=None, description="最近研究时间（ISO-8601）")
    source: str | None = Field(default=None, description="数据源（Provider 名）")
    retrieved_at: str | None = Field(default=None, description="数据获取时间（ISO-8601）")


class CompanyListResponse(BaseModel):
    """GET /api/v1/companies 响应：分页公司列表。"""

    items: list[CompanySummary] = Field(default_factory=list)
    total: int = Field(description="公司总数（用于分页）")


class FinancialMetricSummary(BaseModel):
    """公司详情财务指标摘要（ADR-0006，确定性来源）。"""

    metric: str = Field(description="指标名")
    value: str = Field(description="数值（字符串化，保留精度）")
    period: str = Field(description="期间")
    unit: str | None = Field(default=None, description="单位")
    currency: str | None = Field(default=None, description="币种")
    source: str | None = Field(default=None, description="数据源")


class CompanyDetail(CompanySummary):
    """GET /api/v1/companies/{ticker} 响应（ADR-0006）。"""

    sector: str | None = Field(default=None, description="板块")
    description: str | None = Field(default=None, description="公司简介")
    website: str | None = Field(default=None, description="官网")
    country: str | None = Field(default=None, description="国家/地区")
    exchange: str | None = Field(default=None, description="交易所")
    financials: list[FinancialMetricSummary] = Field(
        default_factory=list, description="财务指标（Provider 提供时）"
    )
    recent_tasks: list[TaskSummary] = Field(
        default_factory=list, description="近期研究任务（复用 tasks 契约）"
    )


class StatsResponse(BaseModel):
    """GET /api/v1/stats 聚合统计（首页 StatCard 数据源）。

    计数均来自真实来源；无数据源的指标诚实为 0（不伪造）。
    """

    companies_count: int = Field(description="已研究公司数（聚合自任务）")
    tasks_count: int = Field(description="研究任务总数")
    evidence_count: int = Field(description="证据引用数（EvidenceStore 计数）")
    calculations_count: int = Field(description="可复现计算数（暂无独立来源，诚实为 0）")


# ---- T808 /audit/{trace_id}（§7.7）----


class AuditResponse(BaseModel):
    """GET /api/v1/audit/{trace_id} 响应（§7.7）。"""

    trace_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)


# ---- §26.9 SSE 事件信封----


class SSEEvent(BaseModel):
    """SSE 统一事件信封（§26.9）。``data`` 为类型相关的 payload。"""

    event_id: str = Field(description="事件 id（UUID4）")
    trace_id: str = Field(description="链路 trace_id")
    timestamp: str = Field(description="ISO-8601 UTC 时间")
    type: str = Field(description="事件类型（§26.9 事件集）")
    data: dict[str, Any] = Field(default_factory=dict)


# ---- §8 Error Contract ----


class ErrorBody(BaseModel):
    """§8 错误信封体。合法 FIN 错误码见 §8.1/§ErrorCode。"""

    code: str = Field(description="FIN 错误码，如 FIN-1004")
    message: str = Field(description="面向用户的稳定 message（不暴露内部细节）")
    retryable: bool = Field(description="是否允许重试（§8.1 Retry 列）")
    trace_id: str = Field(description="链路 trace_id，便于定位")
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """§8 统一错误响应：{error:{...}}。"""

    error: ErrorBody


# ---- 登录（ADR-0019 §4）----

# 口令长度上限：派生开销随口令长度增长，无限长口令会造成 PBKDF2 CPU DoS
# （见 finsage.security 模块说明）。256 远高于任何合理的口令策略。
MAX_PASSWORD_LENGTH = 256


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login 请求（ADR-0019 §4）。"""

    email: str = Field(min_length=1, max_length=255, description="邮箱")
    password: str = Field(
        min_length=1, max_length=MAX_PASSWORD_LENGTH, description="口令（明文，须经 HTTPS 传输）"
    )
    tenant_id: str | None = Field(
        default=None, description="多租户归属时指定租户 id；不指定取用户的默认归属"
    )


class LoginResponse(BaseModel):
    """POST /api/v1/auth/login 响应：签发的身份令牌（ADR-0019 §4）。"""

    access_token: str = Field(description="签名身份令牌（HMAC-SHA256）")
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="有效期（秒）")
    user_id: str = Field(description="用户 id")
    tenant_id: str = Field(description="租户 id")
    role: str = Field(description="该租户内的角色（即令牌 roles 的签发源）")


# ---- FinEval 评估 API（ADR-0022）----

# 每类型取样上限：基准每类 20 条，取 20 即等于全量（超过无意义）。
MAX_LIMIT_PER_TYPE = 20


class EvaluationRequest(BaseModel):
    """POST /api/v1/evaluations 请求（ADR-0022）。

    缺省提交完整 100 条基准；可按任务类型子集 / 每类型条数裁剪（冒烟用）。
    """

    task_types: list[str] | None = Field(
        default=None,
        description="仅评估这些任务类型（retrieval/numeric/citation/abstention/"
        "provider_reliability/decision）；不传为全部",
    )
    limit_per_type: int | None = Field(
        default=None,
        ge=1,
        le=MAX_LIMIT_PER_TYPE,
        description="每个任务类型最多取前 N 条；不传为全部",
    )


class EvaluationResponse(BaseModel):
    """POST /api/v1/evaluations 响应：仅入队，指标经状态端点读取。"""

    task_id: str = Field(description="评估任务 id（查状态 / SSE 流均用它）")
    trace_id: str
    status: Literal["accepted"] = "accepted"
    dataset_name: str
    dataset_version: str
    case_count: int = Field(description="本次将执行的用例数")


class EvaluationRunResponse(BaseModel):
    """GET /api/v1/evaluations/{task_id} 响应：运行状态与指标。

    ``metrics`` 只在完成后有值；``executor`` 标识实际执行器——缺省
    ``DevEvalExecutor`` 表示用例未被真实执行，指标不可当作系统能力评分。
    """

    task_id: str
    status: TaskStatus
    progress: float = Field(ge=0, le=1, description="0..1 进度")
    trace_id: str
    created_at: str = Field(description="ISO-8601 UTC 创建时间")
    error_code: str | None = Field(default=None, description="失败时的 FIN 错误码；否则 null")
    duration_sec: float | None = Field(default=None, description="执行耗时（秒）；未完成为 null")
    run_id: str | None = Field(default=None, description="落库的 evaluation_runs.id；未落库为 null")
    dataset_name: str | None = None
    dataset_version: str | None = None
    case_count: int | None = Field(default=None, description="数据集用例数")
    evaluated_count: int | None = Field(default=None, description="实际被评估的用例数")
    git_commit: str | None = Field(default=None, description="运行时 git commit（可复现性）")
    executor: str | None = Field(default=None, description="实际使用的 CaseExecutor 类名")
    persisted: bool | None = Field(default=None, description="是否已落 evaluation_* 表")
    metrics: dict[str, Any] | None = Field(
        default=None, description="overall + per_type 指标；运行中为 null"
    )


class EvaluationListResponse(BaseModel):
    """GET /api/v1/evaluations 响应：分页评估运行列表。"""

    items: list[EvaluationRunResponse]
    total: int
    limit: int
    offset: int


__all__ = [
    "MAX_QUERY_LENGTH",
    "MarketCode",
    "ChatRequest",
    "ChatResponse",
    "ResearchOptions",
    "ResearchRequest",
    "ResearchResponse",
    "TaskStatus",
    "TaskResponse",
    "TaskSummary",
    "TaskListResponse",
    "DocumentResponse",
    "DocumentSummary",
    "DocumentListResponse",
    "CompanySummary",
    "CompanyListResponse",
    "FinancialMetricSummary",
    "CompanyDetail",
    "StatsResponse",
    "AuditResponse",
    "SSEEvent",
    "ErrorBody",
    "ErrorResponse",
    "MAX_PASSWORD_LENGTH",
    "LoginRequest",
    "LoginResponse",
    "MAX_LIMIT_PER_TYPE",
    "EvaluationRequest",
    "EvaluationResponse",
    "EvaluationRunResponse",
    "EvaluationListResponse",
]