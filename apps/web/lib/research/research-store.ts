/**
 * Research Zustand Store（m10 T1006 / §26.7）。FROZEN contract。
 *
 * 职责边界：
 * - 仅保存 UI/session 状态（activeTaskId / status / progress / answer / traceEvents / 选中项 / error）；
 * - 不作为后端事实源 —— 事实以 m08 API + SSE 事件为准；
 * - 禁止把 Provider、Milvus、MySQL 或原始 SSE stream 对象放入本 store；
 * - 状态迁移一律经 state-machine.ts 的 transition()，非法迁移抛 InvalidTransitionError。
 *
 * 注意：本模块刻意避免任何 Node/浏览器全局副作用，仅作为纯状态容器 + 纯动作，便于测试。
 */
import { create } from "zustand";
import type {
  ApiErrorViewModel,
  CalculationViewModel,
  ResearchAnswerViewModel,
  TraceEventViewModel,
} from "@/lib/api/types";
import { transition, type ResearchStatus } from "./state-machine";

export interface ResearchStore {
  /** 当前活动研究任务的 task_id；无则为 null。 */
  activeTaskId: string | null;
  /** 当前活动任务的 trace_id；无则为 null。 */
  activeTraceId: string | null;
  /** 前端状态机状态（§26.6）。 */
  status: ResearchStatus;
  /** 0..1 进度；无则 0。 */
  progress: number;
  /** 运行时累积的答案文本（answer.delta 聚合 + answer.completed 快照）。 */
  answer: ResearchAnswerViewModel | null;
  /** 有序的 trace 事件（去重后的完整记录，用于 ResearchTrace）。 */
  traceEvents: TraceEventViewModel[];
  /** 当前选中的证据 id（CitationMarker/EvidenceCard 联动）；null 表示未选中。 */
  selectedEvidenceId: string | null;
  /** 当前选中的计算 id；null 表示未选中。 */
  selectedCalculationId: string | null;
  /** 面向用户的错误视图模型；null 表示无错误。 */
  error: ApiErrorViewModel | null;

  /** 起始动作：登记新任务 id + trace id，状态置 submitting。 */
  startTask(taskId: string, traceId: string): void;
  /** 受控状态迁移：经 state-machine 校验后写入。 */
  setStatus(status: ResearchStatus): void;
  setProgress(progress: number): void;
  appendTraceEvent(event: TraceEventViewModel): void;
  mergeAnswerDelta(delta: string): void;
  setAnswer(answer: ResearchAnswerViewModel): void;
  upsertCalculation(calc: CalculationViewModel): void;
  selectEvidence(id: string | null): void;
  selectCalculation(id: string | null): void;
  setError(error: ApiErrorViewModel | null): void;
  reset(): void;
}

function clampProgress(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/**
 * 空答案基线（流式聚合 / 计算卡片插入时作为兜底容器）。
 * disagreement / sentimentSummary 恒为 null：增强信息只由后端下发，前端不伪造占位值。
 */
function emptyAnswer(): ResearchAnswerViewModel {
  return {
    answer: "",
    claims: [],
    evidences: [],
    calculations: [],
    citations: [],
    confidence: 0,
    warnings: [],
    auditId: "",
    disagreement: null,
    sentimentSummary: null,
  };
}

export const useResearchStore = create<ResearchStore>((set, get) => ({
  activeTaskId: null,
  activeTraceId: null,
  status: "idle",
  progress: 0,
  answer: null,
  traceEvents: [],
  selectedEvidenceId: null,
  selectedCalculationId: null,
  error: null,

  startTask(taskId, traceId) {
    set({
      activeTaskId: taskId,
      activeTraceId: traceId,
      status: "submitting",
      progress: 0,
      answer: null,
      traceEvents: [],
      selectedEvidenceId: null,
      selectedCalculationId: null,
      error: null,
    });
  },

  setStatus(status) {
    const next = transition(get().status, status);
    set({ status: next });
  },

  setProgress(progress) {
    set({ progress: clampProgress(progress) });
  },

  appendTraceEvent(event) {
    set((state) => {
      // 按 eventId 去重：重复事件不重复插入（与 SSE 去重一致）。
      if (state.traceEvents.some((e) => e.eventId === event.eventId)) {
        return state;
      }
      return { traceEvents: [...state.traceEvents, event] };
    });
  },

  mergeAnswerDelta(delta) {
    if (!delta) return;
    set((state) => {
      const answer = state.answer ?? emptyAnswer();
      return { answer: { ...answer, answer: answer.answer + delta } };
    });
  },

  setAnswer(answer) {
    set({ answer });
  },

  upsertCalculation(calc) {
    set((state) => {
      const answer = state.answer ?? emptyAnswer();
      const calculations = [...answer.calculations];
      const idx = calculations.findIndex((c) => c.id === calc.id);
      if (idx >= 0) {
        calculations[idx] = calc;
      } else {
        calculations.push(calc);
      }
      return { answer: { ...answer, calculations } };
    });
  },

  selectEvidence(id) {
    set({ selectedEvidenceId: id });
  },

  selectCalculation(id) {
    set({ selectedCalculationId: id });
  },

  setError(error) {
    set({ error });
  },

  reset() {
    set({
      activeTaskId: null,
      activeTraceId: null,
      status: "idle",
      progress: 0,
      answer: null,
      traceEvents: [],
      selectedEvidenceId: null,
      selectedCalculationId: null,
      error: null,
    });
  },
}));