import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import CompaniesPage from "@/app/companies/page";
import type { ApiResult, CompanyListResponseDto } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  api: { companies: { list: vi.fn() } },
}));

const mockedList = vi.mocked(api.companies.list);

function okResult(): ApiResult<CompanyListResponseDto> {
  return {
    ok: true,
    traceId: "tr-1",
    data: {
      total: 1,
      items: [
        {
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
        },
      ],
    },
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CompaniesPage />
    </QueryClientProvider>,
  );
}

describe("CompaniesPage", () => {
  beforeEach(() => {
    mockedList.mockReset();
  });

  it("经 api.companies.list 读取并渲染公司列表（deferred enrichment 两阶段）", async () => {
    // 阶段一：enrich=false 秒回基础列表；阶段二：enrich=true 后台补行情/行业。
    mockedList.mockResolvedValue(okResult());
    renderPage();

    expect(screen.getByText("加载公司库中…")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("宁德时代")).toBeInTheDocument());
    expect(screen.getByText("300750.SZ")).toBeInTheDocument();
    expect(screen.getByText("动力电池")).toBeInTheDocument();
    expect(screen.getByText("184.20")).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledWith({ limit: 200, enrich: false });
    expect(mockedList).toHaveBeenCalledWith({ limit: 200, enrich: true });
  });

  it("api 失败时展示错误信息", async () => {
    mockedList.mockResolvedValueOnce({
      ok: false,
      traceId: "tr-1",
      error: {
        code: "FIN-5001",
        message: "m",
        userMessage: "研究流程执行遇到问题。",
        traceId: "tr-1",
        retryable: true,
      },
    } as ApiResult<CompanyListResponseDto>);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("加载失败")).toBeInTheDocument();
      expect(screen.getByText("研究流程执行遇到问题。")).toBeInTheDocument();
    });
  });
});
