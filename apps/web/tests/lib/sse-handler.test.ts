import { beforeEach, describe, expect, it, vi } from "vitest";
import { applySSEEvent } from "@/lib/research/sse-handler";
import { useResearchStore } from "@/lib/research/research-store";
import type { SSEEnvelopeDto } from "@/lib/api/types";

let seq = 0;

function envelope(
  type: string,
  data: Record<string, unknown> = {},
): SSEEnvelopeDto {
  seq += 1;
  return {
    event_id: `ev-${seq}`,
    trace_id: "tr1",
    timestamp: "2026-01-01T00:00:00Z",
    type,
    data,
  };
}

function storeApi() {
  return useResearchStore.getState();
}

beforeEach(() => {
  seq = 0;
  useResearchStore.getState().reset();
});

describe("applySSEEvent", () => {
  it("workflow.started -> running", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    s.setStatus("queued");
    const onNoGuess = vi.fn();
    const res = applySSEEvent(envelope("workflow.started"), storeApi(), onNoGuess);
    expect(res.applied).toBe(true);
    expect(useResearchStore.getState().status).toBe("running");
    expect(onNoGuess).not.toHaveBeenCalled();
  });

  it("answer.delta -> 追加文本", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    s.setStatus("queued");
    s.setStatus("running");
    const onNoGuess = vi.fn();
    applySSEEvent(envelope("answer.delta", { delta: "你好" }), storeApi(), onNoGuess);
    applySSEEvent(envelope("answer.delta", { delta: "，世界" }), storeApi(), onNoGuess);
    expect(useResearchStore.getState().answer?.answer).toBe("你好，世界");
    expect(onNoGuess).not.toHaveBeenCalled();
  });

  it("answer.delta 从 running 推进 streaming（§26.6 happy path）", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    s.setStatus("queued");
    s.setStatus("running");
    const onNoGuess = vi.fn();
    applySSEEvent(envelope("answer.delta", { delta: "x" }), storeApi(), onNoGuess);
    expect(useResearchStore.getState().status).toBe("streaming");
    expect(onNoGuess).not.toHaveBeenCalled();
  });

  it("answer.delta 在 streaming 幂等（不触发 onNoGuess）", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    s.setStatus("queued");
    s.setStatus("running");
    s.setStatus("streaming");
    const onNoGuess = vi.fn();
    applySSEEvent(envelope("answer.delta", { delta: "y" }), storeApi(), onNoGuess);
    expect(useResearchStore.getState().status).toBe("streaming");
    expect(onNoGuess).not.toHaveBeenCalled();
  });

  it("task.completed -> completed", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    s.setStatus("queued");
    s.setStatus("running");
    s.setStatus("streaming");
    s.setStatus("verifying");
    applySSEEvent(envelope("task.completed"), storeApi(), vi.fn());
    expect(useResearchStore.getState().status).toBe("completed");
  });

  it("阶段事件推进进度条（P1 修复：setProgress 曾被调用）", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    // 进度条默认 0，retrieval.completed 应推进到 0.35。
    applySSEEvent(envelope("retrieval.completed", { hits: 3 }), storeApi(), vi.fn());
    expect(useResearchStore.getState().progress).toBe(0.35);
    // answer.delta 推进到 0.8；只前进不后退。
    applySSEEvent(envelope("answer.delta", { delta: "x" }), storeApi(), vi.fn());
    expect(useResearchStore.getState().progress).toBe(0.8);
    // task.completed 推进到 1.0。
    applySSEEvent(envelope("task.completed"), storeApi(), vi.fn());
    expect(useResearchStore.getState().progress).toBe(1.0);
  });

  it("进度只前进不后退（旧进度不被低阶段覆盖）", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    applySSEEvent(envelope("answer.delta", { delta: "x" }), storeApi(), vi.fn());
    expect(useResearchStore.getState().progress).toBe(0.8);
    applySSEEvent(envelope("retrieval.completed", { hits: 3 }), storeApi(), vi.fn());
    expect(useResearchStore.getState().progress).toBe(0.8);
  });

  it("未冻结 type 触发 onNoGuess 且不应用", () => {
    const onNoGuess = vi.fn();
    const before = useResearchStore.getState().status;
    const res = applySSEEvent(envelope("foo.bar", { x: 1 }), storeApi(), onNoGuess);
    expect(res.applied).toBe(false);
    expect(onNoGuess).toHaveBeenCalledWith(expect.stringContaining("foo.bar"));
    expect(useResearchStore.getState().status).toBe(before);
  });

  it("workflow.started 从 submitting 直接进 running（§26.9 无 queued 事件，不触发 onNoGuess）", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    const onNoGuess = vi.fn();
    applySSEEvent(envelope("workflow.started"), storeApi(), onNoGuess);
    expect(useResearchStore.getState().status).toBe("running");
    expect(onNoGuess).not.toHaveBeenCalled();
  });

  it("非法状态迁移触发 onNoGuess 且不改变状态", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    s.setStatus("queued");
    s.setStatus("running");
    s.setStatus("streaming");
    s.setStatus("verifying");
    s.setStatus("completed");
    const onNoGuess = vi.fn();
    applySSEEvent(envelope("workflow.started"), storeApi(), onNoGuess);
    expect(onNoGuess).toHaveBeenCalledWith(
      expect.stringContaining("invalid transition"),
    );
    expect(useResearchStore.getState().status).toBe("completed");
  });

  it("task.failed -> failed 并写入 error（可恢复）", () => {
    const s = storeApi();
    s.startTask("t", "tr");
    const onNoGuess = vi.fn();
    applySSEEvent(
      envelope("task.failed", {
        error: { code: "FIN-5001", message: "boom", retryable: true },
      }),
      storeApi(),
      onNoGuess,
    );
    expect(useResearchStore.getState().status).toBe("failed");
    expect(useResearchStore.getState().error?.retryable).toBe(true);
    expect(useResearchStore.getState().error?.code).toBe("FIN-5001");
    expect(onNoGuess).not.toHaveBeenCalled();
  });

  describe("trace 状态推导（§1.1：后端未带 status 时按事件类型推导）", () => {
    function lastTraceStatus(): string | undefined {
      const events = useResearchStore.getState().traceEvents;
      return events[events.length - 1]?.status;
    }

    it("retrieval.completed -> trace 状态 completed", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("retrieval.completed", { hits: 3 }), storeApi(), vi.fn());
      expect(lastTraceStatus()).toBe("completed");
    });

    it("calculation.completed -> trace 状态 completed", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("calculation.completed", { count: 2 }), storeApi(), vi.fn());
      expect(lastTraceStatus()).toBe("completed");
    });

    it("workflow.stage 带 status=ok -> trace 状态 completed", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("workflow.stage", { name: "parse", status: "ok" }), storeApi(), vi.fn());
      expect(lastTraceStatus()).toBe("completed");
    });

    it("workflow.stage 的 name 作为 stage 标签", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("workflow.stage", { name: "parse", status: "ok" }), storeApi(), vi.fn());
      const events = useResearchStore.getState().traceEvents;
      expect(events[events.length - 1]?.stage).toBe("parse");
    });

    it("verification.started -> trace 状态 started", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("verification.started"), storeApi(), vi.fn());
      expect(lastTraceStatus()).toBe("started");
    });

    it("answer.delta -> trace 状态 running", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("answer.delta", { delta: "x" }), storeApi(), vi.fn());
      expect(lastTraceStatus()).toBe("running");
    });

    it("显式合法 data.status 优先于类型推导", () => {
      const s = storeApi();
      s.startTask("t", "tr");
      applySSEEvent(envelope("retrieval.completed", { status: "running" }), storeApi(), vi.fn());
      expect(lastTraceStatus()).toBe("running");
    });
  });
});