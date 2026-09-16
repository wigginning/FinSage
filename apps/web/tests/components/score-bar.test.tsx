import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfidenceGauge, FreshnessDot, ScoreBar, confidenceTone, freshnessTone } from "@/components/research/score-bar";

describe("score-bar 证据可视化", () => {
  it("ConfidenceGauge 展示百分比与 aria-label", () => {
    render(<ConfidenceGauge value={0.9} />);
    expect(screen.getByLabelText("置信度 90%")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
  });

  it("ScoreBar 展示标签与百分比", () => {
    render(<ScoreBar label="相关性" value={0.8} />);
    expect(screen.getByText("相关性")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("FreshnessDot 按检索时间给出新鲜度", () => {
    const fresh = new Date(Date.now() - 1000).toISOString();
    const stale = new Date(Date.now() - 40 * 86_400_000).toISOString();
    render(
      <>
        <FreshnessDot iso={fresh} />
        <FreshnessDot iso={stale} />
      </>,
    );
    expect(screen.getByText("新鲜")).toBeInTheDocument();
    expect(screen.getByText("陈旧")).toBeInTheDocument();
  });

  it("confidenceTone 按阈值分档", () => {
    expect(confidenceTone(0.9)).toBe("bg-state-success");
    expect(confidenceTone(0.5)).toBe("bg-state-warning");
    expect(confidenceTone(0.2)).toBe("bg-state-error");
  });

  it("freshnessTone 边界", () => {
    expect(freshnessTone(null).label).toBe("未知");
    expect(freshnessTone(new Date(Date.now() - 10 * 86_400_000).toISOString()).label).toBe("一般");
  });
});
