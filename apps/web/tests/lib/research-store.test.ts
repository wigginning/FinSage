import { beforeEach, describe, expect, it } from "vitest";
import { useResearchStore } from "@/lib/research/research-store";
import type {
  CalculationViewModel,
  TraceEventViewModel,
} from "@/lib/api/types";

function makeEvent(eventId: string): TraceEventViewModel {
  return {
    eventId,
    traceId: "tr1",
    timestamp: "2026-01-01T00:00:00Z",
    type: "workflow.started",
    stage: "workflow",
    status: "running",
    durationMs: null,
    data: {},
  };
}

function makeCalc(id: string, result = "1"): CalculationViewModel {
  return {
    id,
    name: id,
    formula: "a+b",
    inputs: [],
    result,
    unit: null,
    currency: null,
    period: null,
    sourceEvidenceIds: [],
    reproducible: true,
  };
}

describe("useResearchStore", () => {
  beforeEach(() => {
    useResearchStore.getState().reset();
  });

  it("startTask 复位并置 submitting", () => {
    useResearchStore.getState().mergeAnswerDelta("旧文本");
    useResearchStore.getState().appendTraceEvent(makeEvent("e1"));
    useResearchStore.getState().selectEvidence("ev-1");
    useResearchStore.getState().selectCalculation("calc-1");
    useResearchStore.getState().setError({
      code: "FIN-5001",
      message: "m",
      userMessage: "u",
      traceId: "tr1",
      retryable: false,
    });

    useResearchStore.getState().startTask("task-1", "trace-1");

    const s = useResearchStore.getState();
    expect(s.activeTaskId).toBe("task-1");
    expect(s.activeTraceId).toBe("trace-1");
    expect(s.status).toBe("submitting");
    expect(s.progress).toBe(0);
    expect(s.answer).toBeNull();
    expect(s.traceEvents).toEqual([]);
    expect(s.selectedEvidenceId).toBeNull();
    expect(s.selectedCalculationId).toBeNull();
    expect(s.error).toBeNull();
  });

  it("mergeAnswerDelta 累积", () => {
    useResearchStore.getState().mergeAnswerDelta("你好");
    useResearchStore.getState().mergeAnswerDelta("，世界");
    expect(useResearchStore.getState().answer?.answer).toBe("你好，世界");
  });

  it("mergeAnswerDelta 忽略空串", () => {
    useResearchStore.getState().mergeAnswerDelta("");
    expect(useResearchStore.getState().answer).toBeNull();
  });

  it("appendTraceEvent 按 eventId 去重", () => {
    const e = makeEvent("e1");
    useResearchStore.getState().appendTraceEvent(e);
    useResearchStore.getState().appendTraceEvent(e);
    useResearchStore.getState().appendTraceEvent(makeEvent("e2"));
    expect(useResearchStore.getState().traceEvents).toHaveLength(2);
  });

  it("upsertCalculation 新增与替换", () => {
    useResearchStore.getState().upsertCalculation(makeCalc("c1", "1"));
    useResearchStore.getState().upsertCalculation(makeCalc("c1", "2"));
    useResearchStore.getState().upsertCalculation(makeCalc("c2"));
    const calcs = useResearchStore.getState().answer?.calculations ?? [];
    expect(calcs).toHaveLength(2);
    const c1 = calcs.find((c) => c.id === "c1");
    expect(c1?.result).toBe("2");
  });

  it("reset 复位全部状态", () => {
    useResearchStore.getState().startTask("t", "tr");
    useResearchStore.getState().mergeAnswerDelta("x");
    useResearchStore.getState().selectEvidence("ev-1");
    useResearchStore.getState().setError({
      code: "FIN",
      message: "m",
      userMessage: "u",
      traceId: "tr1",
      retryable: false,
    });
    useResearchStore.getState().reset();
    const s = useResearchStore.getState();
    expect(s.activeTaskId).toBeNull();
    expect(s.activeTraceId).toBeNull();
    expect(s.status).toBe("idle");
    expect(s.progress).toBe(0);
    expect(s.answer).toBeNull();
    expect(s.traceEvents).toEqual([]);
    expect(s.selectedEvidenceId).toBeNull();
    expect(s.selectedCalculationId).toBeNull();
    expect(s.error).toBeNull();
  });
});