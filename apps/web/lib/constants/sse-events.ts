/**
 * SSE 事件集（m10 T1007 / §26.9）。FROZEN。
 * 未在此冻结集合内的事件一律按 No-Guess 上报，前端不静默吞掉。
 */
export const SSE_EVENTS = {
  WORKFLOW_STARTED: "workflow.started",
  WORKFLOW_STAGE: "workflow.stage",
  RETRIEVAL_STARTED: "retrieval.started",
  RETRIEVAL_COMPLETED: "retrieval.completed",
  FINANCIAL_DATA_STARTED: "financial_data.started",
  FINANCIAL_DATA_COMPLETED: "financial_data.completed",
  CALCULATION_STARTED: "calculation.started",
  CALCULATION_COMPLETED: "calculation.completed",
  AGENT_STARTED: "agent.started",
  AGENT_COMPLETED: "agent.completed",
  VERIFICATION_STARTED: "verification.started",
  VERIFICATION_COMPLETED: "verification.completed",
  ANSWER_DELTA: "answer.delta",
  ANSWER_COMPLETED: "answer.completed",
  TASK_COMPLETED: "task.completed",
  TASK_FAILED: "task.failed",
  TASK_ABORTED: "task.aborted",
  ERROR: "error",
} as const;

export type SSEEventType = (typeof SSE_EVENTS)[keyof typeof SSE_EVENTS];

/** 冻结事件全集（用于去重/校验）。 */
export const ALL_SSE_EVENTS: readonly string[] = Object.values(SSE_EVENTS);