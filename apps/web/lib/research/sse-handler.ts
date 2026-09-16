/**
 * SSE 事件 → Store 映射（m10 T1007 / §26.9 UI Rules）。FROZEN。
 *
 * 严格遵循 §26.9 UI Rules：
 * workflow.started → 初始化 trace；answer.delta → 推进 streaming 并追加文本；
 * task.completed/failed/aborted → 切状态；answer.completed → 快照；
 * calculation.completed → 增/替 CalculationCard；其余 *_completed → 更新对应 stage trace。
 * 未冻结/非法事件经 onNoGuess 上报。
 *
 * 非法状态迁移（InvalidTransitionError）视为 No-Guess 上报，不导致 UI 崩溃（内部断言不暴露给用户）。
 */
import type {
  SSEEnvelopeDto,
  SentimentSummaryViewModel,
  TraceEventViewModel,
} from "@/lib/api/types";
import { SSE_EVENTS, ALL_SSE_EVENTS } from "@/lib/constants/sse-events";
import type { ResearchStore } from "./research-store";

/**
 * 后端情绪聚合为 snake_case（sentiment_summary / mean_score），在此转前端 camelCase。
 * 缺失 / 结构异常一律返回 null：情绪是"有则展示"的增强信息，不伪造占位。
 */
function toSentimentSummary(raw: unknown): SentimentSummaryViewModel | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const d = raw as Record<string, unknown>;
  const num = (v: unknown, fallback = 0): number =>
    typeof v === "number" && Number.isFinite(v) ? v : fallback;
  const analyzed = num(d.analyzed);
  if (analyzed <= 0) return null;
  return {
    analyzed,
    positive: num(d.positive),
    neutral: num(d.neutral),
    negative: num(d.negative),
    meanScore: num(d.mean_score),
    method: typeof d.method === "string" ? d.method : "keyword_rule_based",
    // 规则法未校准：即使后端漏传也必须为 false（不得默认成"已校准"）。
    calibrated: d.calibrated === true,
  };
}

/** 把统一信封转成前端 TraceEventViewModel。 */
function toTraceEvent(envelope: SSEEnvelopeDto): TraceEventViewModel {
  const data = envelope.data ?? {};
  const stage =
    typeof data.stage === "string"
      ? data.stage
      : typeof data.name === "string"
        ? data.name
        : envelope.type;
  const status = deriveTraceStatus(envelope.type, data);
  const durationMs =
    typeof data.duration_ms === "number" ? data.duration_ms : null;

  return {
    eventId: envelope.event_id,
    traceId: envelope.trace_id,
    timestamp: envelope.timestamp,
    type: envelope.type,
    stage,
    status,
    durationMs,
    data: data as Record<string, unknown>,
  };
}

/**
 * 推导 trace 事件状态（§1.1 修复：后端事件 data 未带 status 时按事件类型推导，
 * 避免所有节点恒显"运行中"）。显式合法 status 优先；workflow.stage 的 "ok" 视为已完成。
 */
function deriveTraceStatus(
  type: string,
  data: Record<string, unknown>,
): TraceEventViewModel["status"] {
  const raw = data.status;
  if (raw === "started" || raw === "running" || raw === "completed" || raw === "failed") {
    return raw;
  }
  if (raw === "ok") return "completed"; // workflow.stage 阶段结果
  if (type.endsWith(".completed")) return "completed";
  if (type.endsWith(".failed")) return "failed";
  if (type.endsWith(".started")) return "started";
  if (type === "workflow.started" || type === "answer.delta") return "running";
  if (type === "task.aborted" || type === "error") return "failed";
  return "running";
}

export interface SseApplyResult {
  /** 是否命中冻结事件且成功应用。 */
  applied: boolean;
}

type StoreApi = Pick<
  ResearchStore,
  | "setStatus"
  | "setProgress"
  | "appendTraceEvent"
  | "mergeAnswerDelta"
  | "setAnswer"
  | "upsertCalculation"
  | "setError"
>;

/** 各阶段事件 → 进度值（0..1）。P1 修复：进度条曾恒 0%（setProgress 从未被调用）。 */
const STAGE_PROGRESS: Readonly<Record<string, number>> = {
  [SSE_EVENTS.WORKFLOW_STARTED]: 0.05,
  [SSE_EVENTS.RETRIEVAL_STARTED]: 0.15,
  [SSE_EVENTS.RETRIEVAL_COMPLETED]: 0.35,
  [SSE_EVENTS.FINANCIAL_DATA_STARTED]: 0.4,
  [SSE_EVENTS.FINANCIAL_DATA_COMPLETED]: 0.55,
  [SSE_EVENTS.CALCULATION_STARTED]: 0.6,
  [SSE_EVENTS.CALCULATION_COMPLETED]: 0.7,
  [SSE_EVENTS.ANSWER_DELTA]: 0.8,
  [SSE_EVENTS.ANSWER_COMPLETED]: 0.9,
  [SSE_EVENTS.VERIFICATION_STARTED]: 0.92,
  [SSE_EVENTS.VERIFICATION_COMPLETED]: 0.97,
  [SSE_EVENTS.TASK_COMPLETED]: 1.0,
};

/**
 * 应用单个 SSE 事件到 store。返回是否已应用。
 * 未知/非法事件路径调用 onNoGuess(raw)，不静默吞掉。
 */
export function applySSEEvent(
  envelope: SSEEnvelopeDto,
  store: StoreApi,
  onNoGuess: (raw: string) => void,
): SseApplyResult {
  const type = envelope.type;
  const frozen = ALL_SSE_EVENTS.includes(type);

  if (!frozen) {
    onNoGuess(`unfrozen SSE type: ${envelope.type}`);
    return { applied: false };
  }

  const trace = toTraceEvent(envelope);
  store.appendTraceEvent(trace);

  // P1：按阶段推进进度条（仅前向推进，避免回退）。
  const stageProgress = STAGE_PROGRESS[type];
  if (stageProgress !== undefined) {
    const current = (store as { progress?: number }).progress ?? 0;
    if (stageProgress > current) {
      store.setProgress(stageProgress);
    }
  }

  const tryStatus = (next: Parameters<typeof store.setStatus>[0]) => {
    try {
      store.setStatus(next);
    } catch {
      onNoGuess(
        `invalid transition on event ${envelope.type} -> ${next} (event_id=${envelope.event_id})`,
      );
    }
  };

  switch (type) {
    case SSE_EVENTS.WORKFLOW_STARTED:
      tryStatus("running");
      break;
    case SSE_EVENTS.RETRIEVAL_STARTED:
    case SSE_EVENTS.FINANCIAL_DATA_STARTED:
    case SSE_EVENTS.CALCULATION_STARTED:
    case SSE_EVENTS.AGENT_STARTED:
    case SSE_EVENTS.RETRIEVAL_COMPLETED:
    case SSE_EVENTS.FINANCIAL_DATA_COMPLETED:
    case SSE_EVENTS.AGENT_COMPLETED:
    case SSE_EVENTS.WORKFLOW_STAGE:
      // stage 记录已通过 appendTraceEvent 写入。
      break;
    case SSE_EVENTS.CALCULATION_COMPLETED: {
      const calc = envelope.data;
      if (
        calc &&
        typeof calc === "object" &&
        !Array.isArray(calc) &&
        typeof (calc as Record<string, unknown>).id === "string"
      ) {
        store.upsertCalculation(calc as never);
      }
      break;
    }
    case SSE_EVENTS.VERIFICATION_STARTED:
      tryStatus("verifying");
      break;
    case SSE_EVENTS.VERIFICATION_COMPLETED:
      // 仍处 VERIFYING，直到 task.completed。
      break;
    case SSE_EVENTS.ANSWER_DELTA: {
      // §26.6 状态机要求 running→streaming→verifying→completed：
      // 首个 answer.delta 推进 streaming（后续 delta 幂等，streaming→streaming 合法）。
      tryStatus("streaming");
      const delta = envelope.data?.delta ?? envelope.data?.text ?? "";
      if (typeof delta === "string" && delta) {
        store.mergeAnswerDelta(delta);
      }
      break;
    }
    case SSE_EVENTS.ANSWER_COMPLETED: {
      const d = envelope.data ?? {};
      if (typeof d === "object" && d !== null && !Array.isArray(d)) {
        const data = d as Record<string, unknown>;
        store.setAnswer({
          answer: typeof data.answer === "string" ? data.answer : "",
          claims: Array.isArray(data.claims) ? (data.claims as never[]) : [],
          evidences: Array.isArray(data.evidences) ? (data.evidences as never[]) : [],
          calculations: Array.isArray(data.calculations) ? (data.calculations as never[]) : [],
          citations: Array.isArray(data.citations) ? (data.citations as never[]) : [],
          confidence: typeof data.confidence === "number" ? data.confidence : 0,
          warnings: Array.isArray(data.warnings) ? (data.warnings as never[]) : [],
          auditId: typeof data.audit_id === "string" ? data.audit_id : "",
          // ADR-0018：分歧度 / 情绪聚合此前后端算得出但组装载荷时丢弃，前端零消费。
          // 缺失或非数字一律回落为 null（UI 不渲染，不伪造占位值）。
          disagreement:
            typeof data.disagreement === "number" && Number.isFinite(data.disagreement)
              ? data.disagreement
              : null,
          sentimentSummary: toSentimentSummary(data.sentiment_summary),
        });
      }
      break;
    }
    case SSE_EVENTS.TASK_COMPLETED:
      tryStatus("completed");
      break;
    case SSE_EVENTS.TASK_FAILED:
      tryStatus("failed");
      if (typeof envelope.data?.error === "object" && envelope.data.error !== null) {
        const err = envelope.data.error as Record<string, unknown>;
        store.setError({
          code: typeof err.code === "string" ? err.code : "FIN-0000",
          message: typeof err.message === "string" ? err.message : "",
          userMessage: "研究任务执行失败。",
          traceId: envelope.trace_id,
          retryable: err.retryable === true,
        });
      }
      break;
    case SSE_EVENTS.TASK_ABORTED:
      tryStatus("aborted");
      break;
    case SSE_EVENTS.ERROR: {
      const err = envelope.data ?? {};
      store.setError({
        code: typeof err.code === "string" ? err.code : "FIN-0000",
        message: typeof err.message === "string" ? err.message : "",
        userMessage: "服务在处理过程中发生错误。",
        traceId: envelope.trace_id,
        retryable: err.retryable === true,
      });
      break;
    }
    default:
      onNoGuess(`unmapped frozen SSE type: ${envelope.type}`);
      return { applied: false };
  }

  return { applied: true };
}