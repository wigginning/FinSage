import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ResearchActions } from "@/components/research/research-actions";

describe("ResearchActions", () => {
  it("failed + errorRetryable 显示重试，不显示中止", () => {
    render(
      <ResearchActions
        status="failed"
        errorRetryable
        onRetry={vi.fn()}
        onAbort={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "重试研究" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "中止" })).not.toBeInTheDocument();
  });

  it("failed + non-retryable 不显示重试", () => {
    render(
      <ResearchActions
        status="failed"
        errorRetryable={false}
        onRetry={vi.fn()}
        onAbort={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "重试研究" })).not.toBeInTheDocument();
  });

  it("aborted 不显示重试与中止", () => {
    render(<ResearchActions status="aborted" onRetry={vi.fn()} onAbort={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "重试研究" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "中止" })).not.toBeInTheDocument();
  });

  it.each(["queued", "running", "streaming", "verifying"])("%s 显示中止", (status) => {
    render(
      <ResearchActions status={status} onRetry={vi.fn()} onAbort={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "中止" })).toBeInTheDocument();
  });

  it("verifying 也可中止（P2：补 verifying→aborted 状态机）", () => {
    const onAbort = vi.fn();
    render(<ResearchActions status="verifying" onRetry={vi.fn()} onAbort={onAbort} />);
    // 首次点击进入确认态，二次点击才触发中止。
    // 必须用 fireEvent（内部包 act）：原生 el.click() 不会让 React 同步刷新状态，
    // 断言会在重渲染前执行（这是本用例此前失败的根因）。
    fireEvent.click(screen.getByRole("button", { name: "中止" }));
    expect(screen.getByRole("button", { name: "确认中止？" })).toBeInTheDocument();
    expect(onAbort).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认中止？" }));
    expect(onAbort).toHaveBeenCalledTimes(1);
  });

  it("中止需二次确认，防误触", () => {
    const onAbort = vi.fn();
    render(<ResearchActions status="running" onRetry={vi.fn()} onAbort={onAbort} />);
    fireEvent.click(screen.getByRole("button", { name: "中止" }));
    expect(onAbort).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "确认中止？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认中止？" }));
    expect(onAbort).toHaveBeenCalledTimes(1);
  });

  it("无 onAbort 时不渲染中止", () => {
    render(<ResearchActions status="running" onRetry={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "中止" })).not.toBeInTheDocument();
  });
});