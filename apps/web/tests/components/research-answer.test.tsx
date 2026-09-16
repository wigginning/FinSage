import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResearchAnswer } from "@/components/research/research-answer";
import type {
  EvidenceViewModel,
  ResearchAnswerViewModel,
} from "@/lib/api/types";

const evidence: EvidenceViewModel = {
  id: "ev-1",
  documentId: "doc-1",
  chunkId: "chunk-1",
  source: "示例来源",
  title: "示例标题",
  page: 12,
  section: "2.1",
  excerpt: "这是证据摘录。",
  publishedAt: "2026-01-01T00:00:00Z",
  retrievedAt: "2026-01-10T00:00:00Z",
  relevanceScore: 0.9,
  authorityScore: 0.8,
  sourceUrl: null,
};

const answer: ResearchAnswerViewModel = {
  answer: "结论正文引用标记[E1]。",
  claims: [
    {
      id: "c1",
      text: "断言一",
      claimType: "fact",
      evidenceIds: ["ev-1"],
      calculationId: null,
      confidence: 0.9,
      verified: true,
    },
  ],
  evidences: [evidence],
  calculations: [
    {
      id: "calc-1",
      name: "营收增速",
      formula: "(b-a)/a",
      inputs: [{ name: "a", value: "100" }],
      result: "20%",
      unit: null,
      currency: null,
      period: "2024",
      sourceEvidenceIds: ["ev-1"],
      reproducible: true,
    },
  ],
  citations: [{ citationId: "cit-1", evidenceId: "ev-1", marker: "[E1]" }],
  confidence: 0.9,
  warnings: [{ code: "W-1", message: "数据存在缺口" }],
  auditId: "audit-1",
  disagreement: null,
  sentimentSummary: null,
};

/** 带分歧度与情绪聚合的答案（ADR-0018）：两者均由后端确定性算出后下发。 */
const answerWithSignals: ResearchAnswerViewModel = {
  ...answer,
  disagreement: 0.42,
  sentimentSummary: {
    analyzed: 3,
    positive: 2,
    neutral: 1,
    negative: 0,
    meanScore: 0.33,
    method: "keyword_rule_based",
    calibrated: false,
  },
};

describe("ResearchAnswer", () => {
  it("渲染正文 / warnings / claims / evidences / calculations", () => {
    render(<ResearchAnswer answer={answer} onSelect={vi.fn()} />);
    expect(screen.getByText("研究结论")).toBeInTheDocument();
    expect(screen.getByLabelText("置信度 90%")).toBeInTheDocument();
    expect(screen.getAllByText(/结论正文/).length).toBeGreaterThan(0);
    expect(screen.getByText(/数据存在缺口/)).toBeInTheDocument();
    expect(screen.getAllByText(/断言一/).length).toBeGreaterThan(0);
    expect(screen.getByText("示例标题")).toBeInTheDocument();
    expect(screen.getByText("营收增速")).toBeInTheDocument();
    expect(screen.getByText("报告期：2024")).toBeInTheDocument();
  });

  it("点击证据卡片定位触发 onSelect('evidence', id)", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ResearchAnswer answer={answer} onSelect={onSelect} />);
    await user.click(screen.getByRole("button", { name: "在答案中定位" }));
    expect(onSelect).toHaveBeenCalledWith("evidence", "ev-1");
  });

  it("点击正文 CitationMarker 触发定位", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ResearchAnswer answer={answer} onSelect={onSelect} />);
    await user.click(
      screen.getByRole("button", { name: "引用标记 [E1]，定位到证据" }),
    );
    expect(onSelect).toHaveBeenCalledWith("evidence", "ev-1");
  });

  it("低置信度时展示诚实降级提示（中性灰，非错误红）", () => {
    const low = { ...answer, confidence: 0.2 };
    render(<ResearchAnswer answer={low} onSelect={vi.fn()} />);
    expect(screen.getByLabelText("证据不足")).toBeInTheDocument();
    expect(screen.getByText(/诚实边界/)).toBeInTheDocument();
  });

  it("高置信度时不展示诚实降级提示", () => {
    render(<ResearchAnswer answer={answer} onSelect={vi.fn()} />);
    expect(screen.queryByLabelText("证据不足")).not.toBeInTheDocument();
  });

  it("ADR-0018：下发分歧度/情绪聚合时渲染徽标，情绪标注未校准", () => {
    render(<ResearchAnswer answer={answerWithSignals} onSelect={vi.fn()} />);
    expect(screen.getByTestId("disagreement-badge")).toHaveTextContent("多空分歧度 42%");
    const badge = screen.getByTestId("sentiment-badge");
    expect(badge).toHaveTextContent("正面 2");
    expect(badge).toHaveTextContent("负面 0");
    // 规则法未校准是硬约束（AGENTS.md §10）：不得冒充权威情绪结论。
    expect(badge).toHaveTextContent("未校准");
  });

  it("ADR-0018：两者为 null 时不渲染任何占位（不伪造）", () => {
    render(<ResearchAnswer answer={answer} onSelect={vi.fn()} />);
    expect(screen.queryByTestId("disagreement-badge")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sentiment-badge")).not.toBeInTheDocument();
  });
});