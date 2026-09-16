import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GlobalSearch } from "@/components/layout/global-search";
import { api } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  api: {
    companies: { list: vi.fn() },
    documents: { list: vi.fn() },
    tasks: { list: vi.fn() },
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const mockedCompanies = vi.mocked(api.companies.list);
const mockedDocuments = vi.mocked(api.documents.list);
const mockedTasks = vi.mocked(api.tasks.list);

function ok<T>(data: T) {
  return { ok: true as const, traceId: "tr", data };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GlobalSearch", () => {
  it("输入关键词后展示分组结果（公司/文档/任务）", async () => {
    mockedCompanies.mockResolvedValue(
      ok({
        items: [
          {
            ticker: "300750",
            name: "宁德时代",
            market: "CN",
            industry: null,
            currency: null,
            price: null,
            change_pct: null,
            research_count: 0,
            last_researched_at: null,
            source: null,
            retrieved_at: null,
          },
        ],
        total: 1,
      }),
    );
    mockedDocuments.mockResolvedValue(
      ok({
        items: [
          {
            document_id: "doc1",
            filename: "宁德时代年报.pdf",
            size: 1024,
            created_at: "2026-08-13T03:12:00Z",
            chunk_count: 3,
            status: "ingested",
            citation_count: 0,
          },
        ],
        total: 1,
      }),
    );
    mockedTasks.mockResolvedValue(
      ok({
        items: [
          {
            task_id: "task1",
            kind: "research",
            status: "completed",
            progress: 1,
            trace_id: "tr",
            created_at: "2026-08-13T03:12:00Z",
            error_code: null,
            query: "评估宁德时代",
            company: null,
            ticker: null,
            duration_sec: null,
          },
        ],
        total: 1,
      }),
    );

    render(<GlobalSearch />);
    await userEvent.type(screen.getByLabelText("全局搜索"), "宁德");

    await waitFor(() => expect(screen.getByText("公司")).toBeInTheDocument());
    expect(screen.getByText("宁德时代")).toBeInTheDocument();
    expect(screen.getByText("文档")).toBeInTheDocument();
    expect(screen.getByText("宁德时代年报.pdf")).toBeInTheDocument();
    expect(screen.getByText("研究任务")).toBeInTheDocument();
    expect(screen.getByText("评估宁德时代")).toBeInTheDocument();
  });

  it("无结果时展示空态", async () => {
    mockedCompanies.mockResolvedValue(ok({ items: [], total: 0 }));
    mockedDocuments.mockResolvedValue(ok({ items: [], total: 0 }));
    mockedTasks.mockResolvedValue(ok({ items: [], total: 0 }));

    render(<GlobalSearch />);
    await userEvent.type(screen.getByLabelText("全局搜索"), "不存在的东西");

    await waitFor(() => expect(screen.getByText("未找到匹配结果。")).toBeInTheDocument());
  });
});
