import { expect, test } from "@playwright/test";
import { envelope, mockStream } from "./support";

test("F007 任务失败：task.failed 注入->失败徽标与错误提示", async ({ page }) => {
  await mockStream(page, [
    envelope("workflow.started", { stage: "workflow", status: "started" }),
    envelope("task.failed", {
      error: { code: "FIN-2001", message: "数据源超时", retryable: false },
    }),
  ]);

  await page.goto("/research/task-e2e-001");

  await expect(page.getByText("失败", { exact: true })).toBeVisible();
  await expect(page.getByText("研究任务执行失败。")).toBeVisible();
  await expect(page.getByRole("button", { name: "重试研究" })).toHaveCount(0);
});

test("F008 任务可重试：可恢复失败显示 Retry", async ({ page }) => {
  await mockStream(page, [
    envelope("workflow.started", { stage: "workflow", status: "started" }),
    envelope("task.failed", {
      error: { code: "FIN-2001", message: "数据源超时", retryable: true },
    }),
  ]);

  await page.goto("/research/task-e2e-001");

  await expect(page.getByText("失败", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试研究" })).toBeVisible();
});

test("F009 任务中止：运行中显示中止并切到已中止", async ({ page }) => {
  await mockStream(page, [
    envelope("workflow.started", { stage: "workflow", status: "started" }),
  ]);

  await page.goto("/research/task-e2e-001");

  await expect(page.getByRole("button", { name: "中止" })).toBeVisible();
  await page.getByRole("button", { name: "中止" }).click();
  await expect(page.getByText("已中止", { exact: true })).toBeVisible();
});