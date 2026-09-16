import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import ResearchPage from "@/app/research/page";
import type { ApiResult, TaskListResponseDto } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  api: { tasks: { list: vi.fn() } },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const mockedList = vi.mocked(api.tasks.list);

function okResult(): ApiResult<TaskListResponseDto> {
  return {
    ok: true,
    traceId: "tr-1",
    data: {
      total: 1,
      items: [
        {
          task_id: "task-1",
          kind: "research",
          status: "completed",
          progress: 1,
          trace_id: "tr-1",
          created_at: "2026-08-13T03:12:00Z",
          error_code: null,
          query: "评估宁德时代 2024 年营收增长",
          company: "宁德时代",
          ticker: "300750",
          duration_sec: null,
        },
      ],
    },
  };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ResearchPage />
    </QueryClientProvider>,
  );
}

describe("ResearchPage 近期任务", () => {
  beforeEach(() => {
    mockedList.mockReset();
  });

  it("经 api.tasks.list 读取近期研究任务并渲染", async () => {
    mockedList.mockResolvedValueOnce(okResult());
    renderPage();

    expect(screen.getByText("加载最近任务中…")).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByText("评估宁德时代 2024 年营收增长")).toBeInTheDocument(),
    );
    expect(screen.getByText("task-1")).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledWith({ kind: "research", limit: 5 });
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
    } as ApiResult<TaskListResponseDto>);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("加载失败")).toBeInTheDocument();
      expect(screen.getByText("研究流程执行遇到问题。")).toBeInTheDocument();
    });
  });
});
