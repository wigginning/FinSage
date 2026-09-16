import { expect, test } from "@playwright/test";
import { envelope, mockStream } from "./support";

test("F010 历史页 → 打开 Research Result", async ({ page }) => {
  // 历史页为静态占位数据；第一个「已完成」行对应 task_18。
  const COMPLETED_TASK_ID = "task_18";

  await mockStream(page, [
    envelope("workflow.started", { stage: "workflow", status: "started" }),
    envelope("task.completed"),
  ]);

  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "研究历史" })).toBeVisible();

  const firstViewLink = page.getByRole("link", { name: "查看结果 →" }).first();
  await expect(firstViewLink).toBeVisible();
  await firstViewLink.click();

  await expect(page).toHaveURL(new RegExp(`/research/${COMPLETED_TASK_ID}$`));
  await expect(page.getByRole("heading", { name: "研究结果" })).toBeVisible();
});