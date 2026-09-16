import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CitationMarker } from "@/components/research/citation-marker";

describe("CitationMarker", () => {
  it("无 onClick 渲染为不可点击的 sup 标记", () => {
    render(<CitationMarker marker="[E1]" evidenceId="ev-1" />);
    expect(screen.getByLabelText("引用标记 [E1]，定位到证据")).toBeInTheDocument();
  });

  it("有 onClick 渲染按钮，点击触发定位回调", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<CitationMarker marker="[E1]" evidenceId="ev-1" onClick={onClick} />);
    const btn = screen.getByRole("button", { name: "引用标记 [E1]，定位到证据" });
    await user.click(btn);
    expect(onClick).toHaveBeenCalledWith("ev-1");
  });
});