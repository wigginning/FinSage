import { expect, test } from "@playwright/test";
import { envelope, mockStream } from "./support";

const SUCCESS_EVENTS = [
  envelope("workflow.started", {
    stage: "workflow",
    status: "started",
    provider: "bge-m3",
    model: "retriever",
  }),
  envelope("retrieval.started", { stage: "retrieval", status: "started" }),
  envelope("retrieval.completed", {
    stage: "retrieval",
    status: "completed",
    duration_ms: 1200,
  }),
  envelope("answer.delta", { delta: "综合多份证据，宁德时代营收保持增长。" }),
  envelope("answer.completed", {
    answer: "综合多份证据，宁德时代营收保持增长。[E1]",
    evidences: [
      {
        id: "ev-1",
        documentId: "doc-1",
        chunkId: "c1",
        source: "示例来源",
        title: "示例证据",
        page: 12,
        section: "2.1",
        excerpt: "这是证据摘录。",
        publishedAt: "2026-01-01T00:00:00Z",
        retrievedAt: "2026-01-10T00:00:00Z",
        relevanceScore: 0.9,
        authorityScore: 0.8,
        sourceUrl: null,
      },
    ],
    calculations: [
      {
        id: "calc-1",
        name: "营收增速",
        formula: "(b-a)/a",
        inputs: [
          { name: "上期营收", value: "100" },
          { name: "本期营收", value: "120" },
        ],
        result: "20%",
        unit: null,
        currency: null,
        period: "2024",
        sourceEvidenceIds: ["ev-1"],
        reproducible: true,
      },
    ],
    citations: [{ citationId: "cit-1", evidenceId: "ev-1", marker: "[E1]" }],
    claims: [
      {
        id: "c1",
        text: "营收增长",
        claimType: "fact",
        evidenceIds: ["ev-1"],
        calculationId: null,
        confidence: 0.9,
        verified: true,
      },
    ],
    confidence: 0.9,
    warnings: [{ code: "W-1", message: "数据存在缺口" }],
    audit_id: "audit-1",
  }),
  envelope("task.completed"),
];

async function openResult(page: import("@playwright/test").Page) {
  await mockStream(page, SUCCESS_EVENTS);
  await page.goto("/research/task-e2e-001");
}

test("F002 流式回答：answer 文本呈现", async ({ page }) => {
  await openResult(page);
  await expect(
    page.getByText(/综合多份证据，宁德时代营收保持增长/),
  ).toBeVisible();
  await expect(page.getByText("置信度 90%")).toBeVisible();
});

test("F003 查看 Evidence", async ({ page }) => {
  await openResult(page);
  await expect(page.getByText("示例证据")).toBeVisible();
  await expect(page.getByText("这是证据摘录。")).toBeVisible();
  await expect(page.getByText("p.12")).toBeVisible();
});

test("F004 查看 Calculation", async ({ page }) => {
  await openResult(page);
  await expect(page.getByText("营收增速")).toBeVisible();
  await expect(page.getByText("20%")).toBeVisible();
  await expect(page.getByText("报告期：2024")).toBeVisible();
});

test("F005 Citation 定位 Evidence", async ({ page }) => {
  await openResult(page);
  await expect(page.getByText("示例证据")).toBeVisible();
  await page.getByRole("button", { name: /引用标记 \[E1\]/ }).click();
  await expect(page.getByText("已选中")).toBeVisible();
});

test("F006 查看 Trace", async ({ page }) => {
  await openResult(page);
  await expect(page.getByRole("heading", { name: "执行链路" })).toBeVisible();
  await expect(page.getByText("provider bge-m3")).toBeVisible();
});