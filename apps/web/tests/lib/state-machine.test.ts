import { describe, expect, it } from "vitest";
import { transition, InvalidTransitionError, type ResearchStatus } from "@/lib/research/state-machine";

describe("state-machine transition", () => {
  it("合法主路径 idle->submitting->queued->running->streaming->verifying->completed", () => {
    let state: ResearchStatus = "idle";
    for (const next of [
      "submitting",
      "queued",
      "running",
      "streaming",
      "verifying",
      "completed",
    ] as const) {
      state = transition(state, next);
    }
    expect(state).toBe("completed");
  });

  it("verifying->failed 合法", () => {
    expect(transition("verifying", "failed")).toBe("failed");
  });

  it("verifying->aborted 合法（P2：补验证阶段可中止）", () => {
    expect(transition("verifying", "aborted")).toBe("aborted");
  });

  it("任意非法迁移抛 InvalidTransitionError", () => {
    expect(() => transition("idle", "completed")).toThrow(InvalidTransitionError);
    expect(() =>
      transition("completed", "failed"),
    ).toThrow("invalid research state transition: completed -> failed");
  });

  it("相同状态幂等", () => {
    expect(transition("running", "running")).toBe("running");
    expect(transition("completed", "completed")).toBe("completed");
    expect(transition("failed", "failed")).toBe("failed");
  });
});