import { expect, test } from "@playwright/test";
import {
  TASK_ID,
  envelope,
  mockResearchCreate,
  mockStream,
} from "./support";

test("F001 新建研究任务：首页提交后跳转结果页", async ({ page }) => {
  await mockResearchCreate(page);
  await mockStream(page, [
    envelope("workflow.started", { stage: "workflow" }),
    envelope("answer.delta", { delta: "任务已接受，开始研究。" }),
    envelope("task.completed"),
  ]);

  await page.goto("/");
  await page.getByLabel("研究主题").fill("评估宁德时代 2024 年营收增长与毛利率变化");
  await page.getByRole("button", { name: "提交研究" }).click();

  await expect(page).toHaveURL(new RegExp(`/research/${TASK_ID}$`));
  await expect(page.getByRole("heading", { name: "研究结果" })).toBeVisible();
  await expect(page.getByText(TASK_ID)).toBeVisible();
});