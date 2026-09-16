import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api/client";
import { ResearchComposer } from "@/components/research/research-composer";
import type { ApiResult, ResearchResponseDto } from "@/lib/api/types";

vi.mock("@/lib/api/client", () => ({
  api: { research: { create: vi.fn() } },
}));

const mockedCreate = vi.mocked(api.research.create);

function okResult(): ApiResult<ResearchResponseDto> {
  return {
    ok: true,
    traceId: "tr-1",
    data: { task_id: "task-1", trace_id: "tr-1", status: "accepted" },
  };
}

describe("ResearchComposer", () => {
  beforeEach(() => {
    mockedCreate.mockReset();
  });

  it("空 query 时提交按钮禁用", () => {
    render(<ResearchComposer onSubmitted={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: "提交研究" }),
    ).toBeDisabled();
  });

  it("空 query 提交被表单校验拦截（aria-invalid 且不调用 api）", () => {
    render(<ResearchComposer onSubmitted={vi.fn()} />);
    const form = screen.getByLabelText("研究提交表单");
    fireEvent.submit(form);
    expect(
      screen.getByLabelText("研究主题"),
    ).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText("请填写研究主题"),
    ).toBeInTheDocument();
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("填写 query 后点提交：调用 api.research.create 并回调 onSubmitted 携带 ResearchTaskViewModel", async () => {
    const user = userEvent.setup();
    const onSubmitted = vi.fn();
    mockedCreate.mockResolvedValueOnce(okResult());

    render(<ResearchComposer onSubmitted={onSubmitted} />);
    await user.type(screen.getByLabelText("研究主题"), "评估宁德时代营收");

    const btn = screen.getByRole("button", { name: "提交研究" });
    expect(btn).toBeEnabled();
    await user.click(btn);

    expect(mockedCreate).toHaveBeenCalledTimes(1);
    expect(mockedCreate).toHaveBeenCalledWith(
      expect.objectContaining({ query: "评估宁德时代营收" }),
    );

    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
    const task = onSubmitted.mock.calls[0][0];
    expect(task).toMatchObject({
      taskId: "task-1",
      traceId: "tr-1",
      status: "queued",
      query: "评估宁德时代营收",
    });
  });

  it("api 失败时展示错误信息且不回调 onSubmitted", async () => {
    const user = userEvent.setup();
    const onSubmitted = vi.fn();
    mockedCreate.mockResolvedValueOnce({
      ok: false,
      traceId: "tr-1",
      error: {
        code: "FIN-1001",
        message: "m",
        userMessage: "请求参数有误，请检查后重试。",
        traceId: "tr-1",
        retryable: false,
      },
    } as ApiResult<ResearchResponseDto>);

    render(<ResearchComposer onSubmitted={onSubmitted} />);
    await user.type(screen.getByLabelText("研究主题"), "评估宁德时代营收");
    await user.click(screen.getByRole("button", { name: "提交研究" }));

    await waitFor(() =>
      expect(
        screen.getByText("请求参数有误，请检查后重试。"),
      ).toBeInTheDocument(),
    );
    expect(onSubmitted).not.toHaveBeenCalled();
  });
});