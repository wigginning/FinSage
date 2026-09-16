import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CalculationCard } from "@/components/research/calculation-card";
import type { CalculationViewModel } from "@/lib/api/types";

const calc: CalculationViewModel = {
  id: "calc-1",
  name: "营收增速",
  formula: "(b-a)/a",
  inputs: [
    { name: "上期", value: "100" },
    { name: "本期", value: "120" },
  ],
  result: "20",
  unit: "亿元",
  currency: "RMB",
  period: "2024",
  sourceEvidenceIds: ["ev-1"],
  reproducible: true,
};

describe("CalculationCard", () => {
  it("渲染 metric/formula/inputs/result/unit/currency/period", () => {
    render(<CalculationCard calc={calc} />);
    expect(screen.getByText("营收增速")).toBeInTheDocument();
    expect(screen.getByText("(b-a)/a")).toBeInTheDocument();
    expect(screen.getByText("上期")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("本期")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    // unit = currency + unit 拼接
    expect(screen.getByText("RMB亿元")).toBeInTheDocument();
    expect(screen.getByText("报告期：2024")).toBeInTheDocument();
    expect(screen.getByText("可复现计算")).toBeInTheDocument();
  });
});