/**
 * API Client（m10 T1002 / §26.8）。
 *
 * 契约：所有接口方法具备 request type / response type / error type / trace propagation。
 * 组件禁止直接 `fetch('/api/...')` —— 一律经本客户端。
 * 由 OpenAPI Contract 生成的客户端在此提供的调用形态下运行；trace_id 透传经 Response header。
 */
import { API_BASE_URL } from "@/lib/constants/api";
import { mapErrorBody, unknownError } from "./error";
import type {
  ApiResult,
  AuditResponseDto,
  CompanyDetailDto,
  CompanyListResponseDto,
  CredentialsProvider,
  DocumentListResponseDto,
  DocumentResponseDto,
  DocumentSummaryDto,
  LoginRequestDto,
  LoginResponseDto,
  ResearchRequestDto,
  ResearchResponseDto,
  StatsResponseDto,
  TaskListResponseDto,
  TaskResponseDto,
} from "./types";

/** 列表接口可选查询参数（status/kind 仅 tasks 支持）。 */
export interface TaskListParams {
  status?: string;
  kind?: string;
  keyword?: string;
  limit?: number;
  offset?: number;
}
export interface ListParams {
  keyword?: string;
  limit?: number;
  offset?: number;
}
export interface CompanyListParams extends ListParams {
  market?: string;
  keyword?: string;
  /** deferred enrichment（§3.1）：false 时跳过 Provider 增强，秒回基础数据。 */
  enrich?: boolean;
}

/** 将可选参数序列化为查询串（无参数返回空串）。 */
function toQuery(params?: TaskListParams | ListParams | CompanyListParams): string {
  if (!params) return "";
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  traceId?: string | null;
  /**
   * 置 true 时跳过 401 闭环处理。
   * 登录请求专用：其 401 语义是"凭据错误"，而非"会话失效"，
   * 若触发跳转会让登录页自己跳自己。
   */
  skipUnauthorizedHandling?: boolean;
}

const TRACE_ID_HEADER = "x-finsage-trace-id";
const TOKEN_STORAGE_KEY = "finsage.access_token";

/** 401 时派发的全局事件名（上层可监听以跳转登录 / 弹提示）。 */
export const UNAUTHORIZED_EVENT = "finsage:unauthorized";

function newTraceId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `trace-${Date.now()}`;
  }
}

function token(): string | null {
  // 约定：令牌存于 sessionStorage（masked，不入 bundle）。存在时可作为 Bearer 附带。
  try {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function clearToken(): void {
  // 401 闭环：清空失效令牌，避免后续请求持续携带死 token 重试。
  try {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* sessionStorage 不可用时静默忽略 */
  }
}

function saveToken(next: string | null): void {
  // 登录成功后落令牌（sessionStorage：标签页级，关闭即失效，不落 localStorage）。
  try {
    if (next) sessionStorage.setItem(TOKEN_STORAGE_KEY, next);
    else sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* sessionStorage 不可用时静默忽略 */
  }
}

export interface ApiClientOptions {
  /** 收到 401 时的回调（如跳登录 / 弹提示）。派发 UNAUTHORIZED_EVENT 之外额外触发。 */
  onUnauthorized?: () => void;
}

export class ApiClient implements CredentialsProvider {
  private readonly onUnauthorized?: () => void;

  constructor(options: ApiClientOptions = {}) {
    this.onUnauthorized = options.onUnauthorized;
  }

  getToken(): string | null {
    return token();
  }

  /** 写入或清除访问令牌（登录成功后 / 登出时使用）。 */
  setToken(next: string | null): void {
    saveToken(next);
  }

  private async request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<ApiResult<T>> {
    const traceId = options.traceId ?? newTraceId();
    const headers: Record<string, string> = {
      accept: "application/json",
      [TRACE_ID_HEADER]: traceId,
    };
    const authToken = this.getToken();
    if (authToken) {
      headers.authorization = `Bearer ${authToken}`;
    }
    let bodyInit: BodyInit | undefined;
    if (options.body !== undefined) {
      if (options.body instanceof FormData) {
        // FormData 由浏览器自动设置 multipart 边界，勿强制 application/json。
        bodyInit = options.body;
      } else {
        headers["content-type"] = "application/json";
        bodyInit = JSON.stringify(options.body);
      }
    }

    let resp: Response;
    try {
      resp = await fetch(`${API_BASE_URL}${path}`, {
        method: options.method ?? "GET",
        headers,
        body: bodyInit,
      });
    } catch (err) {
      return { ok: false, traceId, error: unknownError(err) };
    }

    const respTraceId = resp.headers.get(TRACE_ID_HEADER) ?? traceId;
    if (!resp.ok) {
      // P1 修复（审计 §2.6）：401 表示会话失效。清空死 token、派发全局事件、
      // 触发可选回调 —— 让用户可见"请重新登录"，而非与普通 5xx 一视同仁被吞掉。
      if (resp.status === 401 && !options.skipUnauthorizedHandling) {
        clearToken();
        if (typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent(UNAUTHORIZED_EVENT, { detail: { traceId: respTraceId } }),
          );
        }
        this.onUnauthorized?.();
      }
      try {
        const payload = (await resp.json()) as { error?: unknown };
        return {
          ok: false,
          traceId: respTraceId,
          error: mapErrorBody((payload?.error as never) ?? {}),
        };
      } catch {
        return {
          ok: false,
          traceId: respTraceId,
          error: {
            code: "HTTP_ERROR",
            message: `HTTP ${resp.status}`,
            userMessage: "服务暂时不可用，请稍后重试。",
            traceId: respTraceId,
            retryable: resp.status >= 500,
          },
        };
      }
    }

    try {
      const data = (await resp.json()) as T;
      return { ok: true, traceId: respTraceId, data };
    } catch (err) {
      return { ok: false, traceId: respTraceId, error: unknownError(err) };
    }
  }

  /** POST /api/v1/research —— 创建研究任务（§7.2 / §26.8 api.research.create）。 */
  research = {
    create: (payload: ResearchRequestDto, traceId?: string) =>
      this.request<ResearchResponseDto>("/research", {
        method: "POST",
        body: payload,
        traceId,
      }),
  };

  /** GET /api/v1/tasks/{task_id} —— 任务状态（§7.3 / §26.8 api.tasks.get）。 */
  tasks = {
    get: (taskId: string, traceId?: string) =>
      this.request<TaskResponseDto>(`/tasks/${encodeURIComponent(taskId)}`, { traceId }),
    list: (params?: TaskListParams, traceId?: string) =>
      this.request<TaskListResponseDto>(`/tasks${toQuery(params)}`, { traceId }),
    /** POST /api/v1/tasks/{task_id}/abort —— 中止任务（§1.3 真实中止）。 */
    abort: (taskId: string, traceId?: string) =>
      this.request<TaskResponseDto>(`/tasks/${encodeURIComponent(taskId)}/abort`, {
        method: "POST",
        traceId,
      }),
  };

  /** POST /api/v1/documents —— 上传文档（§7.5 / §26.8 api.documents.create）。 */
  documents = {
    create: (payload: FormData, traceId?: string) =>
      this.request<DocumentResponseDto>("/documents", {
        method: "POST",
        body: payload,
        traceId,
      }),
    list: (params?: ListParams, traceId?: string) =>
      this.request<DocumentListResponseDto>(`/documents${toQuery(params)}`, { traceId }),
    get: (documentId: string, traceId?: string) =>
      this.request<DocumentSummaryDto>(
        `/documents/${encodeURIComponent(documentId)}`,
        { traceId },
      ),
  };

  /** GET /api/v1/evidence/{id} —— 证据（§26.8 api.evidence.get）。 */
  evidence = {
    get: (id: string, traceId?: string) =>
      this.request<Record<string, unknown>>(`/evidence/${encodeURIComponent(id)}`, { traceId }),
  };

  /** Companies API（ADR-0006）：GET /api/v1/companies 与 /companies/{ticker}。 */
  companies = {
    list: (params?: CompanyListParams, traceId?: string) =>
      this.request<CompanyListResponseDto>(`/companies${toQuery(params)}`, { traceId }),
    get: (ticker: string, market?: string, traceId?: string) => {
      const qs = market ? `?market=${encodeURIComponent(market)}` : "";
      return this.request<CompanyDetailDto>(`/companies/${encodeURIComponent(ticker)}${qs}`, {
        traceId,
      });
    },
  };

  /** GET /api/v1/audit/{trace_id} —— 审计链路（§7.7 / §26.8 api.audit.get）。 */
  audit = {
    get: (traceId: string, requestTraceId?: string) =>
      this.request<AuditResponseDto>(`/audit/${encodeURIComponent(traceId)}`, {
        traceId: requestTraceId ?? traceId,
      }),
  };

  /** GET /api/v1/stats —— 聚合统计（首页 StatCard 数据源）。 */
  stats = {
    get: (traceId?: string) => this.request<StatsResponseDto>("/stats", { traceId }),
  };

  /** POST /api/v1/auth/login —— 登录并获取身份令牌（ADR-0019 §4）。 */
  auth = {
    login: (payload: LoginRequestDto, traceId?: string) =>
      this.request<LoginResponseDto>("/auth/login", {
        method: "POST",
        body: payload,
        traceId,
        // 登录的 401 语义是"凭据错误"，不是"会话失效"，故跳过跳转闭环。
        skipUnauthorizedHandling: true,
      }),
  };
}

/** 前台默认 API 客户端单例。 */
export const api = new ApiClient();
export type Api = typeof api;