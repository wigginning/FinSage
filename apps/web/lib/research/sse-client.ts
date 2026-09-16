/**
 * SSE Client（m10 T1007 / §26.9）。FROZEN contract。
 *
 * 连接：`GET /api/v1/tasks/{task_id}/stream`，`Accept: text/event-stream`。
 * 重回：`Last-Event-ID` 或等价的 checkpoint（记录已消费 event_id，重连时携带）。
 * 去重：同一连接/会话内按 event_id 去重，已确认的 event_id 不重复插入。
 * 未冻结事件：一律经 onUnknownEvent 上报（No-Guess），不静默吞掉。
 *
 * 本客户端独立于 Zustand store（stream 对象不得放入 store），仅通过参数把事件应用回调交给外层。
 * 解析函数为纯函数，便于单测。
 */
import type { SSEEnvelopeDto } from "@/lib/api/types";
import { SSE_EVENTS } from "@/lib/constants/sse-events";

/** 最大重连次数（审计 §2.6 P2）：网络抖动重试 ≤5 次即停止，避免无限重连。 */
export const MAX_SSE_RETRIES = 5;

/** 任务终态事件：收到即主动关流，不再重连。 */
const TERMINAL_EVENTS: ReadonlySet<string> = new Set([
  SSE_EVENTS.TASK_COMPLETED,
  SSE_EVENTS.TASK_FAILED,
  SSE_EVENTS.TASK_ABORTED,
]);

/** 单条解析后的 SSE 记录（服务端信封型：SSE `data:` 行承载完整 SSEEnvelopeDto JSON）。 */
export interface ParsedSSEEvent {
  /** SSE 原始行的 id（若存在）；我们的信封用 data.event_id 作为主键。 */
  rawId: string | null;
  /** 完整统一信封，已按 §26.9 校验通过。 */
  envelope: SSEEnvelopeDto;
}

/**
 * 从一段 SSE 原始文本解析出事件。
 * 兼容 `data:` 单行与 `data:` 分行拼接。非法/无 data 行返回 null。
 */
export function parseSSEvent(text: string): ParsedSSEEvent | null {
  let rawId: string | null = null;
  const dataLines: string[] = [];

  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    if (line.startsWith("id:")) {
      rawId = line.slice(3).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5));
    }
  }
  if (dataLines.length === 0) return null;

  try {
    const envelope = JSON.parse(dataLines.join("\n")) as SSEEnvelopeDto;
    if (!envelope || typeof envelope.event_id !== "string" || !envelope.event_id) {
      return null;
    }
    return { rawId, envelope };
  } catch {
    return null;
  }
}

/** SSE 连接回调节点。 */
export interface SseClientHandlers {
  onEvent(event: SSEEnvelopeDto): void;
  /** 未知/未冻结类型或不可解析内容上报（No-Guess）。 */
  onUnknownEvent(raw: string): void;
  onError(error: Error): void;
}

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 15000;

/**
 * 基于 fetch + ReadableStream 的 SSE 客户端（可携带 Authorization / Last-Event-ID 头，
 * EventSource 无法满足）。提供断线重连与按 event_id 去重。
 */
export class SseClient {
  private controller: AbortController | null = null;
  private closed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retries = 0;
  /** 4xx 等致命连接错误：停止重连，但仍需上报给用户（审计 §2.6 P2）。 */
  private fatalError: Error | null = null;
  /** 最近一条已消费的 event_id（checkpoint，用于 Last-Event-ID）。 */
  private lastEventId: string | null = null;
  /** 会话内已消费 event_id 集合（去重）。 */
  private seenEventIds = new Set<string>();

  constructor(
    private readonly token: string | null,
    private readonly handlers: SseClientHandlers,
    private readonly url: string,
  ) {}

  /** 建立连接并开始消费。 */
  async connect(): Promise<void> {
    this.closed = false;
    const controller = new AbortController();
    this.controller = controller;

    const headers: Record<string, string> = {
      accept: "text/event-stream",
      "cache-control": "no-cache",
    };
    if (this.token) headers.authorization = `Bearer ${this.token}`;
    if (this.lastEventId) headers["last-event-id"] = this.lastEventId;

    try {
      const resp = await fetch(this.url, { method: "GET", headers, signal: controller.signal });
      if (!resp.ok || !resp.body) {
        const status = resp.status;
        // 4xx 多为「任务不存在/已终结」等业务态：从响应体解析 FIN 错误码，便于上层降级为中性空态
        // （与 company/document 详情页一致：FIN-1004 → 「暂无数据」而非红字错误）。
        let code: string | undefined;
        let userMessage: string | undefined;
        if (status >= 400 && status < 500) {
          try {
            const body = await resp.text();
            const parsed = JSON.parse(body) as {
              error?: { code?: string; userMessage?: string; message?: string };
            };
            code = parsed.error?.code;
            // 后端 §8 信封用 error.message；前端 api client 约定用 userMessage，两者都兼容。
            userMessage = parsed.error?.userMessage ?? parsed.error?.message;
          } catch {
            /* 响应体非预期 JSON 时忽略，仍按连接错误上报 */
          }
        }
        const error = new Error(`SSE connect failed: HTTP ${status}`) as Error & {
          code?: string;
          userMessage?: string;
        };
        error.code = code;
        error.userMessage = userMessage;
        // 4xx 表示任务不存在或已终结：停止重连（此前会无限重连），
        // 但仍需把错误上报给用户 —— 否则"任务不存在"完全不可见（审计 §2.6 P2）。
        if (status >= 400 && status < 500) {
          this.closed = true;
          this.fatalError = error;
        }
        throw error;
      }
      this.retries = 0;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        if (this.closed) break;
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const parsed = parseSSEvent(chunk);
          if (parsed) {
            this.consume(parsed);
          } else if (chunk.trim()) {
            this.handlers.onUnknownEvent(chunk.trim());
          }
        }
      }
    } catch (err) {
      // 用户主动 close()（含终态事件触发）：不上报、不重连。
      if (this.closed && !this.fatalError) return;
      const error = err instanceof Error ? err : new Error(String(err));
      this.handlers.onError(error);
    }

    if (!this.closed) {
      this.scheduleReconnect();
    }
  }

  /** 主动关闭，不再重连。 */
  close(): void {
    this.closed = true;
    this.controller?.abort();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private consume(parsed: ParsedSSEEvent): void {
    const { envelope } = parsed;
    if (this.seenEventIds.has(envelope.event_id)) {
      return; // 去重：已确认的 event_id 不重复插入
    }
    this.seenEventIds.add(envelope.event_id);
    this.lastEventId = envelope.event_id;
    this.retries = 0;
    this.handlers.onEvent(envelope);
    // 任务终态（completed/failed/aborted）：主动关流，不再重连。
    // 先 onEvent 让外层处理终态，再 close()（close 会 abort 底层流）。
    if (TERMINAL_EVENTS.has(envelope.type)) {
      this.close();
    }
  }

  private scheduleReconnect(): void {
    if (this.closed) return;
    // 最大重试次数（审计 §2.6 P2）：此前对 5xx/网络抖动无限重连。
    if (this.retries >= MAX_SSE_RETRIES) {
      this.closed = true;
      this.handlers.onError(
        new Error(`SSE 连接失败已达最大重试次数（${MAX_SSE_RETRIES}），已停止重连`),
      );
      return;
    }
    const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** this.retries, RECONNECT_MAX_DELAY_MS);
    this.retries += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }

  /** 当前 checkpoint（用于测试/状态上报）。 */
  get lastEventIdValue(): string | null {
    return this.lastEventId;
  }
}