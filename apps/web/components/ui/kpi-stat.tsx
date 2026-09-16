"use client";

/**
 * KPIStat — 顶部统计卡（替代 app/page.tsx 里的 StatCard + 走查发现 KPI 数字层级倒挂）。
 * 修复：把"标签放最显眼位置 + 数字次要"调整为"数字最大、tabular、可加载/错误态诚实降级"。
 * value="" 表示加载中（骨架），"—" 表示错误/无数据（与现状 statValue 兼容）。
 */
import type { LucideIcon } from "lucide-react";
import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "./skeleton";

export interface KPIStatProps {
  icon?: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  className?: string;
}

export function KPIStat({ icon: Icon = TrendingUp, label, value, sub, className }: KPIStatProps) {
  const loading = value === "" || value === "…";
  return (
    <div className={cn("rounded-lg border border-border bg-card card-surface p-4", className)}>
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-4 w-4" aria-hidden="true" />
        <span className="text-[11px] font-medium uppercase tracking-wider">{label}</span>
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-8 w-20" />
      ) : (
        <p className="mt-2 text-3xl font-semibold tabular leading-none">{value}</p>
      )}
      {sub ? <p className="mt-2 text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}
