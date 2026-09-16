"use client";

/**
 * StateView — 统一占位态（加载中 / 空数据 / 无匹配 / 出错 / 成功）。
 *
 * 走查发现：页面里"加载失败"常是一条裸红字、"暂无数据"是一行灰字 —— 无图标、无说明、
 * 无出口，体感极差。本组件用「图标 + 标题 + 描述 + 可选行动区」统一替换这些散落模式。
 *
 * 命名说明：`components/research/status.tsx` 已占用 EmptyState/ErrorState/... 之名，
 * 故此处命名 StateView（语义也更准：它覆盖的不止 empty 一种态）。
 */
import type { LucideIcon } from "lucide-react";
import { CheckCircle2, Inbox, Info, Loader2, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StateViewVariant = "empty" | "loading" | "error" | "info" | "success";

export interface StateViewProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  variant?: StateViewVariant;
  /** 紧凑模式：去掉外框与大幅留白，用于卡片内嵌占位。 */
  compact?: boolean;
  className?: string;
}

const DEFAULT_ICON: Record<StateViewVariant, LucideIcon> = {
  empty: Inbox,
  loading: Loader2,
  error: TriangleAlert,
  info: Info,
  success: CheckCircle2,
};

const TONE: Record<StateViewVariant, string> = {
  empty: "border-border bg-muted/40 text-muted-foreground",
  loading: "border-border bg-muted/40 text-muted-foreground",
  error: "border-state-error/30 bg-state-error-bg text-state-error",
  info: "border-state-info/30 bg-state-info-bg text-state-info",
  success: "border-state-success/30 bg-state-success-bg text-state-success",
};

const ICON_TONE: Record<StateViewVariant, string> = {
  empty: "bg-muted text-muted-foreground",
  loading: "bg-muted text-muted-foreground",
  error: "bg-state-error/10 text-state-error",
  info: "bg-state-info/10 text-state-info",
  success: "bg-state-success/10 text-state-success",
};

const TITLE_TONE: Record<StateViewVariant, string> = {
  empty: "text-foreground",
  loading: "text-foreground",
  error: "text-state-error",
  info: "text-state-info",
  success: "text-state-success",
};

export function StateView({
  icon,
  title,
  description,
  action,
  variant = "empty",
  compact = false,
  className,
}: StateViewProps) {
  const Icon = icon ?? DEFAULT_ICON[variant];
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg text-center",
        compact ? "px-4 py-6" : "border px-6 py-10",
        compact && variant === "empty" ? "bg-muted/30" : null,
        !compact ? TONE[variant] : null,
        className,
      )}
      role={variant === "error" ? "alert" : "status"}
      aria-busy={variant === "loading" || undefined}
    >
      <span
        className={cn(
          "flex items-center justify-center rounded-full",
          compact ? "h-9 w-9" : "h-12 w-12",
          ICON_TONE[variant],
        )}
        aria-hidden="true"
      >
        <Icon
          className={cn(
            compact ? "h-5 w-5" : "h-6 w-6",
            variant === "loading" ? "animate-spin" : null,
          )}
        />
      </span>
      <div className="space-y-1">
        <p className={cn("text-sm font-semibold", TITLE_TONE[variant])}>{title}</p>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
