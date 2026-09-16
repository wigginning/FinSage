"use client";

/**
 * Table — 数据表格原子组件（替代散落的 `overflow-hidden rounded-lg border ... <table> ... <thead> ...`）。
 * 设计：紧凑密度（与设计令牌 1440px 容器对齐），表头用 `bg-muted/50` 极淡灰，
 * 行 hover 用 `bg-muted/40`，列内边距统一 `px-4 py-3`。
 */
import { forwardRef, type HTMLAttributes, type ThHTMLAttributes, type TdHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Table = forwardRef<HTMLTableElement, HTMLAttributes<HTMLTableElement>>(
  function Table({ className, ...props }, ref) {
    return (
      <div className="overflow-hidden rounded-lg border border-border bg-card card-surface">
        <table
          ref={ref}
          className={cn("w-full text-left text-sm", className)}
          {...props}
        />
      </div>
    );
  },
);

export function TableHeader({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn("border-b border-border bg-muted/50 text-xs text-muted-foreground", className)}
      {...props}
    />
  );
}

export function TableBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TableRow({ className, ...props }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("transition-colors hover:bg-muted/40", className)} {...props} />;
}

export function TableHead({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("px-4 py-2.5 font-medium", className)} {...props} />;
}

export function TableCell({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-4 py-3", className)} {...props} />;
}
