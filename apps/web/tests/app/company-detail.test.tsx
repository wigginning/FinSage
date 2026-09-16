import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import CompanyDetailPage from "@/app/companies/[ticker]/page";
import type { ApiResult, CompanyDetailDto } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  api: { companies: { get: vi.fn() } },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ ticker: "300750.SZ" }),
}));

const mockedGet = vi.mocked(api.companies.get);

function okResult(): ApiResult<CompanyDetailDto> {
  return {
    ok: true,
    traceId: "tr-1",
    data: {
      ticker: "300750.SZ",
      name: "宁德时代",
      market: "CN",
      industry: "动力电池",
      currency: "CNY",
      price: "184.20",
      change_pct: null,
      research_count: 2,
      last_researched_at: "2026-08-13T03:12:00Z",
      source: "fake",
      retrieved_at: "2026-08-24T00:00:00Z",
      sector: "电池",
      description: "动力电池龙头",
      website: null,
      country: "CN",
      exchange: "深圳证券交易所",
      financials: [
        {
          metric: "revenue",
          value: "362060000000",
          period: "2024",
          unit: "CNY",
          currency: "CNY",
          source: "fake",
        },
      ],
      recent_tasks: [
        {
          task_id: "task-1",
          kind: "research",
          status: "completed",
          progress: 1,
          trace_id: "tr-1",
          created_at: "2026-08-13T03:12:00Z",
          error_code: null,
          query: "评估宁德时代营收",
          company: "宁德时代",
          ticker: "300750.SZ",
          duration_sec: null,
        },
      ],
    },
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CompanyDetailPage />
    </QueryClientProvider>,
  );
}

describe("CompanyDetailPage", () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it("经 api.companies.get 读取并渲染公司详情", async () => {
    mockedGet.mockResolvedValueOnce(okResult());
    renderPage();

    expect(screen.getByText("加载 300750.SZ 的公司档案中…")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("heading", { name: "宁德时代" })).toBeInTheDocument());
    expect(screen.getByText("300750.SZ")).toBeInTheDocument();
    expect(screen.getByText("营业总收入")).toBeInTheDocument();
    expect(screen.getByText("评估宁德时代营收")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("300750.SZ");
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
    } as ApiResult<CompanyDetailDto>);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("暂未收录该公司")).toBeInTheDocument();
      expect(screen.getByText("返回公司库")).toBeInTheDocument();
    });
  });
});
