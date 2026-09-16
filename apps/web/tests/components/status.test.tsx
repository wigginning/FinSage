import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  StatusBadge,
  TaskStatus,
  LoadingState,
  EmptyState,
  ErrorState,
  SuccessState,
} from "@/components/research/status";

describe("TaskStatus / StatusBadge", () => {
  it.each([
    ["idle", "待开始"],
    ["submitting", "提交中"],
    ["queued", "排队中"],
    ["running", "运行中"],
    ["streaming", "流式回答"],
    ["verifying", "交叉验证"],
    ["completed", "已完成"],
    ["failed", "失败"],
    ["aborted", "已中止"],
  ])("状态 %s 渲染文案 %s", (status, label) => {
    render(<TaskStatus status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("StatusBadge 渲染指定状态", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });
});

describe("占位组件", () => {
  it("LoadingState 渲染默认文案与 status 角色", () => {
    render(<LoadingState />);
    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("LoadingState 支持自定义 label", () => {
    render(<LoadingState label="正在生成" />);
    expect(screen.getByText("正在生成")).toBeInTheDocument();
  });

  it("EmptyState 渲染 title/description", () => {
    render(<EmptyState title="暂无数据" description="可稍后重试" />);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
    expect(screen.getByText("可稍后重试")).toBeInTheDocument();
  });

  it("SuccessState 渲染 title/description", () => {
    render(<SuccessState title="已完成" description="全部通过" />);
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("全部通过")).toBeInTheDocument();
  });

  it("ErrorState 渲染错误与 traceId，点击重试回调 onRetry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<ErrorState userMessage="出错了" traceId="tr-123" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("出错了")).toBeInTheDocument();
    expect(screen.getByText("追踪 ID：tr-123")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("ErrorState 无 onRetry 不渲染重试按钮", () => {
    render(<ErrorState userMessage="出错了" />);
    expect(screen.getByText("出错了")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
  });
});