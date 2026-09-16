import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiClient, UNAUTHORIZED_EVENT } from "@/lib/api/client";

const ORIG_FETCH = globalThis.fetch;

function mockFetchOnce(status: number, body: unknown) {
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  globalThis.fetch = ORIG_FETCH;
  vi.restoreAllMocks();
});

describe("api.tasks.abort", () => {
  it("POST /tasks/{id}/abort 并返回任务状态", async () => {
    mockFetchOnce(200, {
      task_id: "t1",
      status: "aborted",
      progress: 0.5,
      trace_id: "tr1",
      result: null,
    });
    const res = await api.tasks.abort("t1");
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.data.status).toBe("aborted");
    }
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/v1/tasks/t1/abort");
    expect(init.method).toBe("POST");
  });

  it("任务不存在时返回错误（FIN-1004）", async () => {
    mockFetchOnce(404, {
      error: { code: "FIN-1004", message: "not found", retryable: false },
    });
    const res = await api.tasks.abort("nope");
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe("FIN-1004");
    }
  });
});

describe("401 登录闭环", () => {
  it("401 清空失效 token、触发回调并派发全局事件", async () => {
    sessionStorage.setItem("finsage.access_token", "expired");
    const onUnauthorized = vi.fn();
    const client = new ApiClient({ onUnauthorized });
    const events: string[] = [];
    const handler = () => events.push("unauth");
    window.addEventListener(UNAUTHORIZED_EVENT, handler);

    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "FIN-401", message: "unauthorized" } }), {
        status: 401,
        headers: { "content-type": "application/json", "x-finsage-trace-id": "tr-x" },
      }),
    ) as unknown as typeof fetch;

    const res = await client.tasks.get("t1");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.error.code).toBe("FIN-401");
    // 闭环：失效 token 被清空，避免持续携带死 token 重试。
    expect(sessionStorage.getItem("finsage.access_token")).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(events).toHaveLength(1);

    window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  });

  it("非 401 错误不触发闭环", async () => {
    sessionStorage.setItem("finsage.access_token", "alive");
    const onUnauthorized = vi.fn();
    const client = new ApiClient({ onUnauthorized });
    mockFetchOnce(500, { error: { code: "HTTP_ERROR", message: "boom" } });

    const res = await client.tasks.get("t1");
    expect(res.ok).toBe(false);
    expect(sessionStorage.getItem("finsage.access_token")).toBe("alive");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("api.auth.login（ADR-0019 §4）", () => {
  it("POST /auth/login 并返回身份令牌", async () => {
    mockFetchOnce(200, {
      access_token: "tok-abc",
      token_type: "bearer",
      expires_in: 3600,
      user_id: "u1",
      tenant_id: "t1",
      role: "admin",
    });
    const res = await api.auth.login({ email: "a@b.com", password: "pw" });
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.data.access_token).toBe("tok-abc");
      expect(res.data.role).toBe("admin");
    }
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/v1/auth/login");
    expect(init.method).toBe("POST");
  });

  it("登录失败（401）不触发登录跳转闭环", async () => {
    // 登录的 401 语义是"凭据错误"而非"会话失效"；若派发事件会让登录页自己跳自己。
    const client = new ApiClient();
    const events: string[] = [];
    const handler = () => events.push("unauth");
    window.addEventListener(UNAUTHORIZED_EVENT, handler);

    mockFetchOnce(401, { error: { code: "FIN-1002", message: "invalid credentials" } });
    const res = await client.auth.login({ email: "a@b.com", password: "bad" });

    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.error.code).toBe("FIN-1002");
    expect(events).toHaveLength(0);

    window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  });
});

describe("api.setToken", () => {
  it("写入后 getToken 可读，置 null 可清除", () => {
    const client = new ApiClient();
    expect(client.getToken()).toBeNull();
    client.setToken("tok-xyz");
    expect(client.getToken()).toBe("tok-xyz");
    expect(sessionStorage.getItem("finsage.access_token")).toBe("tok-xyz");
    client.setToken(null);
    expect(client.getToken()).toBeNull();
  });
});
