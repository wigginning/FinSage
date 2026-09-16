"use client";

/**
 * Tag — 小型块状标签（用于市场分类 CN/HK，替代 `<span class="rounded bg-muted px-1.5 py-0.5 text-xs">`）。
 * 与 Badge 的区别：Tag 是纯文本块、无圆点、无 dot；用于行内密集信息（如表格第一列后的市场代码）。
 */
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: "neutral" | "muted";
}

export function Tag({ className, tone = "muted", ...props }: TagProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px]",
        tone === "muted" ? "bg-muted text-muted-foreground" : "bg-muted text-foreground",
        className,
      )}
      {...props}
    />
  );
}
