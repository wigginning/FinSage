import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotificationBell } from "@/components/layout/notification-bell";
import { api } from "@/lib/api/client";
import type { TaskSummaryDto } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  api: {
    tasks: { list: vi.fn() },
  },
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const mockedTasks = vi.mocked(api.tasks.list);

function ok<T>(data: T) {
  return { ok: true as const, traceId: "tr", data };
}

function task(over: Partial<TaskSummaryDto> = {}): TaskSummaryDto {
  return {
    task_id: "task1",
    kind: "research",
    status: "completed",
    progress: 1,
    trace_id: "tr",
    created_at: "2026-08-26T03:16:06+00:00",
    error_code: null,
    query: "评估宁德时代",
    company: "宁德时代",
    ticker: "300750",
    duration_sec: null,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  push.mockClear();
  localStorage.clear();
});

describe("NotificationBell", () => {
  it("展示终态任务的未读角标与通知列表", async () => {
    mockedTasks.mockResolvedValue(
      ok({
        items: [
          task({ task_id: "t1", status: "completed", query: "评估宁德时代" }),
          task({ task_id: "t2", status: "failed", query: "查询失败任务" }),
        ],
        total: 2,
      }),
    );

    render(<NotificationBell />);
    await waitFor(() => expect(mockedTasks).toHaveBeenCalled());

    await userEvent.click(screen.getByLabelText("通知"));
    expect(screen.getByText("评估宁德时代")).toBeInTheDocument();
    expect(screen.getByText("查询失败任务")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
  });

  it("点击通知跳转结果页并标记已读", async () => {
    mockedTasks.mockResolvedValue(
      ok({ items: [task({ task_id: "t1", status: "completed", query: "评估宁德时代" })], total: 1 }),
    );

    render(<NotificationBell />);
    await waitFor(() => expect(mockedTasks).toHaveBeenCalled());

    await userEvent.click(screen.getByLabelText("通知"));
    await userEvent.click(screen.getByText("评估宁德时代"));

    expect(push).toHaveBeenCalledWith("/research/t1");
    // 已读后角标消失
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });

  it("全部已读清空角标", async () => {
    mockedTasks.mockResolvedValue(
      ok({ items: [task({ task_id: "t1", status: "completed", query: "评估宁德时代" })], total: 1 }),
    );

    render(<NotificationBell />);
    await waitFor(() => expect(mockedTasks).toHaveBeenCalled());

    await userEvent.click(screen.getByLabelText("通知"));
    expect(screen.getByText("1")).toBeInTheDocument();
    await userEvent.click(screen.getByText("全部已读"));
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });
});
