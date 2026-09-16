"use client";

/**
 * ResearchTrace（m10 T1012 / §26.10）。
 * 展示完整 Research 事件链路：每个阶段的 stage / status（带色点）/ 耗时 / provider / model / tool。
 * provider/model/tool 从事件 data（Record<string, unknown>）里读取，缺失时省略。
 * 空数组时显示空态文案。
 */
import type { TraceEventViewModel } from "@/lib/api/types";
import { ListTree } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { StateView } from "@/components/ui/state-view";

const TRACE_STATUS_DOT: Record<string, string> = {
  started: "bg-state-queued",
  running: "bg-state-streaming",
  completed: "bg-state-success",
  failed: "bg-state-error",
};

const TRACE_STATUS_LABEL: Record<string, string> = {
  started: "已启动",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

/** 阶段状态 → Badge 语义色（与 research/status.tsx 的状态体系保持一致）。 */
const TRACE_STATUS_VARIANT: Record<
  string,
  "queued" | "streaming" | "success" | "error" | "neutral"
> = {
  started: "queued",
  running: "streaming",
  completed: "success",
  failed: "error",
};

function readStr(data: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const raw = data[key];
    if (typeof raw === "string" && raw.trim()) return raw;
  }
  return null;
}

export function ResearchTrace({ events }: { events: TraceEventViewModel[] }) {
  if (events.length === 0) {
    return (
      <StateView
        icon={ListTree}
        title="暂无执行链路记录"
        description="任务开始后，各阶段事件将在此展示。"
      />
    );
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="px-4 py-2.5">
        <CardTitle className="text-sm">
          执行链路{" "}
          <span className="text-xs font-normal text-muted-foreground">({events.length} 条事件)</span>
        </CardTitle>
      </CardHeader>
      <ol className="divide-y divide-border" aria-label="研究执行链路">
        {events.map((event) => {
          const provider = readStr(event.data, ["provider", "provider_name"]);
          const model = readStr(event.data, ["model", "model_name", "model_id"]);
          const tool = readStr(event.data, ["tool", "tool_name", "agent"]);
          const dot = cn(
            "mt-1.5 h-2 w-2 shrink-0 rounded-full",
            TRACE_STATUS_DOT[event.status] ?? "bg-muted-foreground",
          );
          return (
            <li key={event.eventId} className="flex items-start gap-3 px-4 py-3">
              <span className={dot} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-mono text-sm font-medium">{event.stage || event.type}</span>
                  <Badge size="sm" variant={TRACE_STATUS_VARIANT[event.status] ?? "neutral"}>
                    {TRACE_STATUS_LABEL[event.status] ?? event.status}
                  </Badge>
                  {event.durationMs != null ? (
                    <span className="tabular text-xs text-muted-foreground">
                      {(event.durationMs / 1000).toFixed(1)}s
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-xs text-muted-foreground">
                  {provider ? <span>provider {provider}</span> : null}
                  {model ? <span>model {model}</span> : null}
                  {tool ? <span>tool {tool}</span> : null}
                  <span className="truncate text-muted-foreground/60" title={event.traceId ?? ""}>
                    trace {event.traceId ? event.traceId.slice(0, 8) : "—"}
                  </span>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}