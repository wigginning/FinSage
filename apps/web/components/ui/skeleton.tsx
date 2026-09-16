"use client";

/**
 * Skeleton — 走查发现多处用 "加载中…" 文本占位，体感差。改用骨架屏。
 * 用 `bg-muted` + `animate-pulse` 与设计令牌一致；支持 `SkeletonText` 多行占位。
 */
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="h-3"
          style={{ width: `${Math.max(40, 100 - i * 15)}%` } as React.CSSProperties}
        />
      ))}
    </div>
  );
}
