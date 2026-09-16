/**
 * 前端常量（m10 T1001 / §26.3 路由 / §26.9 SSE 事件集）。
 * 事件集为 §26.9 冻结集合；未冻结事件需报告（No-Guess）。
 */

/** API 基础地址（服务端/浏览器通用）。 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8237/api/v1";

/** SSE 基础地址。 */
export const SSE_BASE_URL =
  process.env.NEXT_PUBLIC_SSE_BASE_URL ?? "http://localhost:8237/api/v1";

/** 前端路由（与 §26.3 对齐，参数为稳定 API 标识符，非 UI 标签）。 */
export const ROUTES = {
  home: "/",
  research: "/research",
  researchResult: (taskId: string) => `/research/${taskId}`,
  companies: "/companies",
  company: (ticker: string) => `/companies/${ticker}`,
  documents: "/documents",
  document: (documentId: string) => `/documents/${documentId}`,
  history: "/history",
  settings: "/settings",
} as const;

/** 市场枚举（§7.2 ResearchRequest.market）。 */
export const MARKETS = ["CN", "US", "HK", "GLOBAL"] as const;

/** 任务状态（§7.3 / §26.5 ResearchTaskViewModel.status）。 */
export const TASK_STATUSES = [
  "queued",
  "running",
  "completed",
  "failed",
  "aborted",
] as const;

/** §8.1 FIN 错误码 → 稳定的面向用户提示（§26.12 规定不直接展示后端 code）。 */
export const FIN_CODE_TO_USER: Record<string, string> = {
  "FIN-1001": "请求参数有误，请检查后重试。",
  "FIN-1002": "登录状态已失效，请重新登录。",
  "FIN-1003": "当前账号无权限执行该操作。",
  "FIN-1004": "请求的资源不存在。",
  "FIN-2001": "金融数据源暂时没有响应，请稍后重试。",
  "FIN-2002": "金融数据源暂不可用。",
  "FIN-2003": "金融数据源请求过于频繁，请稍后重试。",
  "FIN-2004": "金融数据源返回了无法解析的内容。",
  "FIN-2101": "不同数据源返回的数据存在差异，系统已暂停高置信度结论。",
  "FIN-3001": "检索服务暂不可用。",
  "FIN-3003": "当前知识库和数据源没有找到足够证据支持该结论。",
  "FIN-4001": "出于合规边界，本轮研究请求被规则拦截。",
  "FIN-4002": "证据不足，系统将不做确定性回答。",
  "FIN-5001": "研究流程执行遇到问题。",
  "FIN-5002": "研究流程执行超时。",
};