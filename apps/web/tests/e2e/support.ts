import type { Page, Route } from "@playwright/test";

export const TASK_ID = "task-e2e-001";
export const TRACE_ID = "trace-e2e-001";

let seq = 0;

/** 构造一个统一信封（§26.9），event_id 保证唯一以便 SSE 去重语义可用。 */
export function envelope(
  type: string,
  data: Record<string, unknown> = {},
): Record<string, unknown> {
  seq += 1;
  return {
    event_id: `${type}-${seq}`,
    trace_id: TRACE_ID,
    timestamp: new Date().toISOString(),
    type,
    data,
  };
}

export function sseBody(events: Array<Record<string, unknown>>): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

/** 拦截 POST /api/v1/research，返回固定任务创建响应。 */
export async function mockResearchCreate(page: Page): Promise<void> {
  await page.route("**/api/v1/research", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: TASK_ID,
        trace_id: TRACE_ID,
        status: "accepted",
      }),
    });
  });
}

/** 拦截 GET /api/v1/tasks/<id>/stream，注入一组 SSE 事件。 */
export async function mockStream(
  page: Page,
  events: Array<Record<string, unknown>>,
): Promise<void> {
  await page.route("**/api/v1/tasks/*/stream", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "cache-control": "no-cache" },
      body: sseBody(events),
    });
  });
}