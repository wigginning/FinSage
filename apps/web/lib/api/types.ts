/**
 * FinSage 前端类型契约（m10 T1002）。
 *
 * 来源：
 * - 服务端请求/响应模型：m08 `src/finsage/api/schemas.py`（§7.1–7.7、§26.9 信封、§8 错误）。
 * - 前端 ViewModel：§26.5 冻结 interface。
 * - 错误视图模型：§26.12 ApiErrorViewModel。
 *
 * 这些类型在存在 OpenAPI Spec 后应改由规范化生成器输出；此前以本文件为准（不手写重复、
 * 禁止组件内裸 fetch —— 组件一律经 lib/api/client.ts）。
 */

// --- §7 请求/响应 ---

export interface ResearchOptionsDto {
  include_calculation: boolean;
  include_evidence: boolean;
  max_evidence: number;
}

export interface ResearchRequestDto {
  query: string;
  company?: string;
  ticker?: string;
  market?: string;
  session_id?: string | null;
  options?: ResearchOptionsDto;
}

export interface ResearchResponseDto {
  task_id: string;
  trace_id: string;
  status: "accepted";
}

export interface ChatRequestDto {
  session_id?: string | null;
  message: string;
  stream?: boolean;
}

export interface ChatResponseDto {
  task_id: string;
  session_id: string;
  trace_id: string;
  status: "accepted";
}

export type TaskStatusDto = "queued" | "running" | "completed" | "failed" | "aborted";

export interface TaskResponseDto {
  task_id: string;
  status: TaskStatusDto;
  progress: number;
  trace_id: string;
  result: unknown | null;
}

export interface DocumentResponseDto {
  document_id: string;
  status: "accepted";
}

export interface AuditResponseDto {
  trace_id: string;
  events: Record<string, unknown>[];
}

// --- §7.3 / §7.5 列表与读接口 DTO（前端 m10 接线）---

export interface TaskSummaryDto {
  task_id: string;
  kind: string;
  status: TaskStatusDto;
  progress: number;
  trace_id: string;
  created_at: string;
  error_code: string | null;
  query: string | null;
  company: string | null;
  ticker: string | null;
  duration_sec: number | null;
}

export interface TaskListResponseDto {
  items: TaskSummaryDto[];
  total: number;
}

export interface DocumentSummaryDto {
  document_id: string;
  filename: string;
  size: number;
  created_at: string;
  chunk_count: number;
  status: string;
  citation_count: number;
}

export interface DocumentListResponseDto {
  items: DocumentSummaryDto[];
  total: number;
}

// --- Companies API（ADR-0006，Proposed）---

export interface CompanySummaryDto {
  ticker: string;
  name: string;
  market: string;
  industry: string | null;
  currency: string | null;
  price: string | null;
  change_pct: string | null;
  research_count: number;
  last_researched_at: string | null;
  source: string | null;
  retrieved_at: string | null;
}

export interface CompanyListResponseDto {
  items: CompanySummaryDto[];
  total: number;
}

export interface FinancialMetricSummaryDto {
  metric: string;
  value: string;
  period: string;
  unit: string | null;
  currency: string | null;
  source: string | null;
}

export interface CompanyDetailDto extends CompanySummaryDto {
  sector: string | null;
  description: string | null;
  website: string | null;
  country: string | null;
  exchange: string | null;
  financials: FinancialMetricSummaryDto[];
  recent_tasks: TaskSummaryDto[];
}

export interface StatsResponseDto {
  companies_count: number;
  tasks_count: number;
  evidence_count: number;
  calculations_count: number;
}

// --- §8 错误信封 ---

export interface ErrorBodyDto {
  code: string;
  message: string;
  retryable: boolean;
  trace_id: string;
  details: Record<string, unknown>;
}

export interface ErrorResponseDto {
  error: ErrorBodyDto;
}

// --- §26.9 SSE 事件信封 ---

export interface SSEEnvelopeDto {
  event_id: string;
  trace_id: string;
  timestamp: string;
  type: string;
  data: Record<string, unknown>;
}

// --- §26.5 前端 ViewModels（FROZEN） ---

export interface ResearchTaskViewModel {
  taskId: string;
  sessionId: string | null;
  traceId: string;
  status: "queued" | "running" | "completed" | "failed" | "aborted";
  progress: number;
  query: string;
  createdAt: string;
  updatedAt: string;
  result: ResearchAnswerViewModel | null;
  error: ApiErrorViewModel | null;
}

/** 证据集情绪聚合（ADR-0011 / ADR-0018）。calibrated 恒为 false —— 规则法未校准，UI 必须标注。 */
export interface SentimentSummaryViewModel {
  analyzed: number;
  positive: number;
  neutral: number;
  negative: number;
  meanScore: number;
  method: string;
  calibrated: boolean;
}

export interface ResearchAnswerViewModel {
  answer: string;
  claims: ClaimViewModel[];
  evidences: EvidenceViewModel[];
  calculations: CalculationViewModel[];
  citations: CitationViewModel[];
  confidence: number;
  warnings: WarningViewModel[];
  auditId: string;
  /** 多空分歧度 0..1（ADR-0009）；null 表示未运行辩论节点，UI 不渲染。 */
  disagreement: number | null;
  /** 证据情绪聚合（ADR-0018）；null 表示未做情绪富化，UI 不渲染。 */
  sentimentSummary: SentimentSummaryViewModel | null;
}

export interface ClaimViewModel {
  id: string;
  text: string;
  claimType: string;
  evidenceIds: string[];
  calculationId: string | null;
  confidence: number;
  verified: boolean;
}

export interface EvidenceViewModel {
  id: string;
  documentId: string;
  chunkId: string;
  source: string;
  title: string;
  page: number | null;
  section: string | null;
  excerpt: string;
  publishedAt: string | null;
  retrievedAt: string;
  relevanceScore: number;
  authorityScore: number;
  sourceUrl: string | null;
}

export interface CalculationInputViewModel {
  name: string;
  value: string;
}

export interface CalculationViewModel {
  id: string;
  name: string;
  formula: string;
  inputs: CalculationInputViewModel[];
  result: string;
  unit: string | null;
  currency: string | null;
  period: string | null;
  sourceEvidenceIds: string[];
  reproducible: boolean;
}

export interface CitationViewModel {
  citationId: string;
  evidenceId: string;
  marker: string;
}

export interface TraceEventViewModel {
  eventId: string;
  traceId: string;
  timestamp: string;
  type: string;
  stage: string;
  status: "started" | "running" | "completed" | "failed";
  durationMs: number | null;
  data: Record<string, unknown>;
}

export interface WarningViewModel {
  code: string;
  message: string;
}

// --- §26.12 ApiErrorViewModel ---

export interface ApiErrorViewModel {
  code: string;
  message: string;
  userMessage: string;
  traceId: string | null;
  retryable: boolean;
}

export interface ApiSuccess<T> {
  ok: true;
  traceId: string | null;
  data: T;
}

export interface ApiFailure {
  ok: false;
  traceId: string | null;
  error: ApiErrorViewModel;
}

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

/** HTTP 凭据提供者：返回访问令牌（不含则按未登录处理）。 */
export interface CredentialsProvider {
  getToken(): string | null;
}

/* ---- 登录（ADR-0019 §4 / §6）---- */

/** POST /api/v1/auth/login 请求。字段对齐后端 LoginRequest。 */
export interface LoginRequestDto {
  email: string;
  password: string;
  /** 多租户归属时指定租户；不传则取用户的默认归属。 */
  tenant_id?: string | null;
}

/** POST /api/v1/auth/login 响应。字段对齐后端 LoginResponse。 */
export interface LoginResponseDto {
  access_token: string;
  token_type: "bearer";
  /** 有效期（秒）。 */
  expires_in: number;
  user_id: string;
  tenant_id: string;
  /** 该租户内的角色（viewer / member / admin / owner）。 */
  role: string;
}