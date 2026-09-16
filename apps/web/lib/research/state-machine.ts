/**
 * Research 前端状态机（m10 T1005 / §26.6）。FROZEN transitions。
 *
 * IDLE→SUBMITTING→QUEUED→RUNNING→STREAMING→VERIFYING→COMPLETED
 * 异常路径：SUBMITTING/QUEUED/RUNNING/STREAMING/VERIFYING → FAILED 或 ABORTED。
 *
 * 说明：§26.9 冻结 SSE 事件集没有 queued 事件；后端建任务后经 SSE 直接发
 * workflow.started，因此允许 SUBMITTING→RUNNING（跳过 QUEUED），使 happy path 可达 COMPLETED。
 * P2：验证阶段亦可中止（verifying→aborted），修复审计 §2.8 指出的状态机缺失。
 */

export const RESEARCH_STATES = [
  "idle",
  "submitting",
  "queued",
  "running",
  "streaming",
  "verifying",
  "completed",
  "failed",
  "aborted",
] as const;

export type ResearchStatus = (typeof RESEARCH_STATES)[number];

const ALLOWED_TRANSITIONS: Readonly<Record<ResearchStatus, readonly ResearchStatus[]>> = {
  idle: ["submitting"],
  submitting: ["queued", "running", "failed", "aborted"],
  queued: ["running", "failed", "aborted"],
  running: ["streaming", "failed", "aborted"],
  streaming: ["verifying", "running", "failed", "aborted"],
  verifying: ["completed", "failed", "aborted"],
  completed: [],
  failed: [],
  aborted: [],
};

export class InvalidTransitionError extends Error {
  constructor(from: ResearchStatus, to: ResearchStatus) {
    super(`invalid research state transition: ${from} -> ${to}`);
    this.name = "InvalidTransitionError";
  }
}

/**
 * 依据当前状态与目标状态做合法迁移校验。返回新状态；
 * 非法迁移抛 InvalidTransitionError（调用方应视为内部断言错误，不应导致 UI 崩溃的静默错误态）。
 */
export function transition(from: ResearchStatus, to: ResearchStatus): ResearchStatus {
  if (from === to) {
    return from;
  }
  const allowed = ALLOWED_TRANSITIONS[from];
  if (allowed.includes(to)) {
    return to;
  }
  throw new InvalidTransitionError(from, to);
}