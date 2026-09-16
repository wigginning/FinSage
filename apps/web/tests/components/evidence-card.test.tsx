import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvidenceCard } from "@/components/research/evidence-card";
import type { EvidenceViewModel } from "@/lib/api/types";

const evidence: EvidenceViewModel = {
  id: "ev-1",
  documentId: "doc-1",
  chunkId: "chunk-1",
  source: "示例来源",
  title: "示例标题",
  page: 12,
  section: "2.1",
  excerpt: "摘录内容",
  publishedAt: "2026-01-01T00:00:00Z",
  retrievedAt: "2026-01-10T00:00:00Z",
  relevanceScore: 0.9,
  authorityScore: 0.8,
  sourceUrl: "https://example.com/report",
};

describe("EvidenceCard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("渲染 source/authority/page/section/excerpt/published/retrieved", () => {
    render(<EvidenceCard evidence={evidence} onSelect={vi.fn()} />);
    expect(screen.getByText("示例标题")).toBeInTheDocument();
    expect(screen.getByText("示例来源")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument(); // authorityScore
    expect(screen.getByText("90%")).toBeInTheDocument(); // relevanceScore
    expect(screen.getByText("相关性")).toBeInTheDocument();
    expect(screen.getByText("权威度")).toBeInTheDocument();
    expect(screen.getByText("p.12")).toBeInTheDocument();
    expect(screen.getByText("2.1")).toBeInTheDocument(); // section 值
    expect(screen.getByText("摘录内容")).toBeInTheDocument();
    expect(screen.getByText("在答案中定位")).toBeInTheDocument();
    expect(screen.getByText("打开来源")).toBeInTheDocument();
  });

  it("点击复制引用调用 navigator.clipboard.writeText", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<EvidenceCard evidence={evidence} />);
    await user.click(screen.getByRole("button", { name: "复制引用" }));

    expect(writeText).toHaveBeenCalledTimes(1);
    const citation = writeText.mock.calls[0][0] as string;
    expect(citation).toContain("示例来源");
    expect(citation).toContain("p.12");
    expect(citation).toContain("§2.1");
    expect(screen.getByText("已复制引用")).toBeInTheDocument();
  });

  it("点击选择触发 onSelect(id)", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<EvidenceCard evidence={evidence} onSelect={onSelect} />);
    await user.click(screen.getByRole("button", { name: "在答案中定位" }));
    expect(onSelect).toHaveBeenCalledWith("ev-1");
  });
});