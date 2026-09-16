import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import DocumentDetailPage from "@/app/documents/[documentId]/page";
import type { ApiResult, DocumentSummaryDto } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  api: { documents: { get: vi.fn() } },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ documentId: "doc-1" }),
}));

const mockedGet = vi.mocked(api.documents.get);

function okResult(): ApiResult<DocumentSummaryDto> {
  return {
    ok: true,
    traceId: "tr-1",
    data: {
      document_id: "doc-1",
      filename: "宁德时代 2024 年年度报告.pdf",
      size: 8806400,
      created_at: "2026-08-11T00:00:00Z",
      chunk_count: 42,
      status: "ingested",
      citation_count: 3,
    },
  };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <DocumentDetailPage />
    </QueryClientProvider>,
  );
}

describe("DocumentDetailPage", () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it("加载成功后展示后端返回的文档元数据", async () => {
    mockedGet.mockResolvedValueOnce(okResult());
    renderPage();

    expect(screen.getByText("加载文档详情中…")).toBeInTheDocument();

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "宁德时代 2024 年年度报告.pdf" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getAllByText("doc-1").length).toBeGreaterThan(0);
    expect(screen.getByText("8.4 MB")).toBeInTheDocument();
    expect(screen.getByText("2026-08-11")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument(); // 分块数
    expect(screen.getByText("已入库")).toBeInTheDocument(); // 状态
    expect(screen.getByText("3")).toBeInTheDocument(); // 被引用次数
    expect(mockedGet).toHaveBeenCalledWith("doc-1");
  });

  it("api 失败时展示错误信息", async () => {
    mockedGet.mockResolvedValueOnce({
      ok: false,
      traceId: "tr-1",
      error: {
        code: "FIN-1004",
        message: "m",
        userMessage: "请求的资源不存在。",
        traceId: "tr-1",
        retryable: false,
      },
    } as ApiResult<DocumentSummaryDto>);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("暂无该文档")).toBeInTheDocument();
      expect(screen.getByText("返回文档库")).toBeInTheDocument();
    });
  });
});
