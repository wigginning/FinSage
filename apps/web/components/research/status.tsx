"use client";

/**
 * 状态呈现（m10 T1013 / §26.13）。禁单一全局 Spinner。
 * - StatusBadge / TaskStatus：任务状态徽标（queued/running/streaming/verifying/completed/failed/aborted）。
 * - LoadingState/EmptyState/ErrorState/SuccessState：全局占位组件。
 *
 * 重构（组件库收口）：本文件原本自带一套手写 pill 与占位块，与 `components/ui/` 的
 * Badge / StateView / Button 重复。现全部改为委托原子组件 —— **对外 API 与 DOM 契约不变**
 * （文案、role、可点击名称均保持原样，`tests/components/status.test.tsx` 无需改动）。
 */
import type { ResearchStatus } from "@/lib/research/state-machine";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StateView } from "@/components/ui/state-view";

type StatusMeta = {
  label: string;
  variant: "queued" | "streaming" | "verifying" | "success" | "error" | "aborted" | "neutral";
  dotClassName: string;
};

const STATUS_META: Record<string, StatusMeta> = {
  idle: { label: "待开始", variant: "queued", dotClassName: "bg-state-queued" },
  submitting: { label: "提交中", variant: "queued", dotClassName: "bg-state-queued" },
  queued: { label: "排队中", variant: "queued", dotClassName: "bg-state-queued" },
  running: { label: "运行中", variant: "queued", dotClassName: "bg-state-queued" },
  streaming: { label: "流式回答", variant: "streaming", dotClassName: "bg-state-streaming" },
  verifying: { label: "交叉验证", variant: "verifying", dotClassName: "bg-state-verifying" },
  completed: { label: "已完成", variant: "success", dotClassName: "bg-state-success" },
  failed: { label: "失败", variant: "error", dotClassName: "bg-state-error" },
  aborted: { label: "已中止", variant: "aborted", dotClassName: "bg-state-aborted" },
};

const UNKNOWN_META: StatusMeta = {
  label: "",
  variant: "neutral",
  dotClassName: "bg-muted-foreground",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const meta = STATUS_META[status] ?? { ...UNKNOWN_META, label: status };
  return (
    <Badge variant={meta.variant} size="md" className={cn("gap-1.5 px-2.5", className)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dotClassName)} aria-hidden="true" />
      {meta.label}
    </Badge>
  );
}

export function TaskStatus({ status, className }: { status: string; className?: string }) {
  return <StatusBadge status={status} className={className} />;
}

export function LoadingState({ label = "加载中…" }: { label?: string }) {
  return <StateView variant="loading" title={label} />;
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return <StateView variant="empty" title={title} description={description} />;
}

export function ErrorState({
  userMessage,
  onRetry,
  traceId,
}: {
  userMessage: string;
  onRetry?: () => void;
  traceId?: string | null;
}) {
  return (
    <StateView
      variant="error"
      title={userMessage}
      description={traceId ? `追踪 ID：${traceId}` : undefined}
      action={
        onRetry ? (
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    />
  );
}

export function SuccessState({ title, description }: { title: string; description?: string }) {
  return <StateView variant="success" title={title} description={description} />;
}

export type { ResearchStatus };
