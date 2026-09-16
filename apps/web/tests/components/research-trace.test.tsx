import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResearchTrace } from "@/components/research/research-trace";
import type { TraceEventViewModel } from "@/lib/api/types";

function event(over: Partial<TraceEventViewModel> = {}): TraceEventViewModel {
  return {
    eventId: "e1",
    traceId: "trace-abcdefgh",
    timestamp: "2026-01-01T00:00:00Z",
    type: "workflow.started",
    stage: "工作流",
    status: "running",
    durationMs: 1500,
    data: {
      provider: "bge-m3",
      model: "rerank",
      tool: "milvus_retriever",
    },
    ...over,
  };
}

describe("ResearchTrace", () => {
  it("空数组显示空态文案", () => {
    render(<ResearchTrace events={[]} />);
    expect(screen.getByText(/暂无执行链路记录/)).toBeInTheDocument();
  });

  it("渲染 stage/status/duration/provider/model/tool", () => {
    render(<ResearchTrace events={[event()]} />);
    expect(screen.getByText("工作流")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("1.5s")).toBeInTheDocument();
    expect(screen.getByText("provider bge-m3")).toBeInTheDocument();
    expect(screen.getByText("model rerank")).toBeInTheDocument();
    expect(screen.getByText("tool milvus_retriever")).toBeInTheDocument();
  });

  it("缺失 provider/model/tool 时省略", () => {
    render(<ResearchTrace events={[event({ data: {} })]} />);
    expect(screen.queryByText(/provider /)).not.toBeInTheDocument();
    expect(screen.queryByText(/model /)).not.toBeInTheDocument();
    expect(screen.queryByText(/tool /)).not.toBeInTheDocument();
  });
});