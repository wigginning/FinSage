"use client";

/**
 * Card — 容器原子组件（替代散落各处的 `rounded-lg border border-border bg-card`）。
 * 走查发现：11 处页面/组件手写同一组类，是 #1 重复模式。
 * 视觉对齐：finsage-ui 卡片规范（极轻投影 `card-surface`，padding 等级 4/5/6）。
 */
import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const SURFACE = "rounded-lg border border-border bg-card card-surface";

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function Card({ className, ...props }, ref) {
    return <div ref={ref} className={cn(SURFACE, className)} {...props} />;
  },
);

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-b border-border px-5 py-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-base font-semibold tracking-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("mt-1 text-sm text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />;
}

export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center justify-end gap-2 border-t border-border px-5 py-3", className)} {...props} />;
}
