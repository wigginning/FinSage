"use client";

/**
 * Badge — 状态/分类徽章（替代散落的 success/warning/error pill 与市场分类小标签）。
 * variant 对齐 globals.css `--state-*-bg` 设计令牌，明暗双模自适应。
 * size 区分密集表格（sm）与详情区（md）。
 */
import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1 rounded-full font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        neutral: "bg-muted text-muted-foreground",
        success: "bg-state-success-bg text-state-success",
        warning: "bg-state-warning-bg text-state-warning",
        error: "bg-state-error-bg text-state-error",
        info: "bg-state-info-bg text-state-info",
        // 状态语义（对齐 research/status.tsx）
        queued: "bg-state-queued-bg text-state-queued",
        streaming: "bg-state-streaming-bg text-state-streaming",
        verifying: "bg-state-verifying-bg text-state-verifying",
        aborted: "bg-state-aborted-bg text-state-aborted",
        // 中性块状（市场分类 CN/HK）
        solid: "bg-muted text-foreground",
      },
      size: {
        sm: "px-1.5 py-0.5 text-[11px]",
        md: "px-2 py-0.5 text-xs",
      },
    },
    defaultVariants: { variant: "neutral", size: "md" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {
  /** 前置圆点（用于 "运行中" 状态）。 */
  dot?: ReactNode;
}

export function Badge({ className, variant, size, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badge({ variant, size }), className)} {...props}>
      {dot ? <span aria-hidden="true">{dot}</span> : null}
      {children}
    </span>
  );
}
