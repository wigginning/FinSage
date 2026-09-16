import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_SSE_RETRIES,
  SseClient,
  parseSSEvent,
} from "@/lib/research/sse-client";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const ENVELOPE = (type: string, eventId: string) => ({
  event_id: eventId,
  trace_id: "tr1",
  timestamp: "2026-01-01T00:00:00Z",
  type,
  data: {},
});

function makeClient(handlers: {
  onEvent?: (e: { type: string }) => void;
  onUnknownEvent?: (raw: string) => void;
  onError?: (e: Error) => void;
}) {
  return new SseClient(
    null,
    {
      onEvent: handlers.onEvent ?? vi.fn(),
      onUnknownEvent: handlers.onUnknownEvent ?? vi.fn(),
      onError: handlers.onError ?? vi.fn(),
    },
    "http://localhost/stream",
  );
}

describe("parseSSEvent", () => {
  it("解析单行 data: 信封", () => {
    const raw = `data: {"event_id":"e1","trace_id":"tr1","timestamp":"2026-01-01T00:00:00Z","type":"workflow.started","data":{}}`;
    const parsed = parseSSEvent(raw);
    expect(parsed).not.toBeNull();
    expect(parsed!.envelope.event_id).toBe("e1");
    expect(parsed!.envelope.type).toBe("workflow.started");
    expect(parsed!.rawId).toBeNull();
  });

  it("支持 id: 行与多行 data: 拼接", () => {
    const raw = [
      "id: raw-1",
      "data: {\"event_id\":\"e2\"",
      "data: ,\"type\":\"answer.delta\",\"data\":{\"delta\":\"x\"}}",
    ].join("\n");
    const parsed = parseSSEvent(raw);
    expect(parsed).not.toBeNull();
    expect(parsed!.rawId).toBe("raw-1");
    expect(parsed!.envelope.event_id).toBe("e2");
    expect(parsed!.envelope.type).toBe("answer.delta");
  });

  it("空文本 / 无 data 行 返回 null", () => {
    expect(parseSSEvent("")).toBeNull();
    expect(parseSSEvent("event: foo")).toBeNull();
    expect(parseSSEvent("id: raw-1\n\n")).toBeNull();
  });

  it("data 非合法 JSON 返回 null", () => {
    expect(parseSSEvent("data: not-json")).toBeNull();
  });

  it("data 为 JSON 但缺 event_id 返回 null", () => {
    expect(parseSSEvent("data: {\"type\":\"x\",\"data\":{}}")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// SseClient 连接行为（审计 §2.6 P2：404 可见 / 重连上限 / 终态关流）
// ---------------------------------------------------------------------------


it("404 停止重连但仍上报错误（此前用户完全看不到“任务不存在”）", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 404, statusText: "Not Found" }),
  );
  const onError = vi.fn();
  const client = makeClient({ onError });

  await client.connect();

  expect(onError).toHaveBeenCalledTimes(1);
  expect(onError.mock.calls[0][0].message).toContain("404");
  // 4xx 后不再重连：fetch 只被调用一次（初始连接）。
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("4xx 响应体含 FIN 错误码时透传到 onError（FIN-1004 → 上层降级为空态）", async () => {
  const body = JSON.stringify({
    error: { code: "FIN-1004", message: "task x not found", userMessage: "资源不存在" },
  });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(body, { status: 404, headers: { "content-type": "application/json" } }),
  );
  const onError = vi.fn();
  const client = makeClient({ onError });

  await client.connect();

  expect(onError).toHaveBeenCalledTimes(1);
  const err = onError.mock.calls[0][0] as Error & { code?: string; userMessage?: string };
  expect(err.code).toBe("FIN-1004");
  expect(err.userMessage).toBe("资源不存在");
});


it("5xx 重连有上限：达 MAX_SSE_RETRIES 后停止并上报", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(null, { status: 500 }),
  );
  const onError = vi.fn();
  const client = makeClient({ onError });

  await client.connect(); // 首次失败 + 已安排首次重连
  expect(fetchMock).toHaveBeenCalledTimes(1);

  // 持续推进虚拟时间，直到触达"最大重试次数"上报（每次推进可连发多个已到期定时器，
  // 因此以终止条件为准，不假定每次推进只触发一次重连）。
  let guard = 0;
  while (guard < 30 && !String(onError.mock.calls.at(-1)?.[0].message).includes("最大重试次数")) {
    await vi.advanceTimersByTimeAsync(60_000);
    guard += 1;
  }

  // 首次 + MAX_SSE_RETRIES 次重连 = 1+N 次请求，之后停止。
  // onError 比 fetch 多一次：最后一次是"已达最大重试次数"的终止上报。
  expect(fetchMock).toHaveBeenCalledTimes(1 + MAX_SSE_RETRIES);
  expect(onError).toHaveBeenCalledTimes(2 + MAX_SSE_RETRIES);
  expect(onError.mock.calls.at(-1)?.[0].message).toContain("最大重试次数");
  expect(vi.getTimerCount()).toBe(0);
});


it("收到任务终态事件后主动关流，不再重连", async () => {
  const envelope = ENVELOPE("task.completed", "e-final");
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(`data: ${JSON.stringify(envelope)}\n\n`),
      );
    },
  });
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(stream, { status: 200 }));
  const onEvent = vi.fn();
  const onError = vi.fn();
  const client = makeClient({ onEvent, onError });

  await client.connect();

  expect(onEvent).toHaveBeenCalledTimes(1);
  expect(onEvent.mock.calls[0][0].type).toBe("task.completed");
  expect(onError).not.toHaveBeenCalled();
  // 终态后不再重连：fetch 只被调用一次。
  expect(fetchMock).toHaveBeenCalledTimes(1);
});