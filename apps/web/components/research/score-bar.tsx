"use client";

/**
 * 证据可视化语言（§4.2）：把"可信几成 / 证据哪来的 / 来源多新鲜"变成一眼可核查的视觉。
 * - ConfidenceGauge：结论置信度色带（高=success / 中=warning / 低=error）。
 * - ScoreBar：证据相关性 / 权威度迷你进度条。
 * - FreshnessDot：来源新鲜度渐变（fresh→stale 用 emerald→amber→muted）。
 */
import { cn } from "@/lib/utils";

export function confidenceTone(value: number): string {
  if (value >= 0.7) return "bg-state-success";
  if (value >= 0.4) return "bg-state-warning";
  return "bg-state-error";
}

export function ConfidenceGauge({ value, className }: { value: number; className?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className={cn("flex items-center gap-2", className)} aria-label={`置信度 ${pct}%`}>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div
          className={cn("h-full rounded-full transition-all", confidenceTone(value))}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="tabular text-xs font-medium">{pct}%</span>
    </div>
  );
}

export function ScoreBar({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="w-12 shrink-0 text-muted-foreground/70">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div
          className={cn("h-full rounded-full", confidenceTone(value))}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-9 shrink-0 text-right tabular text-muted-foreground">{pct}%</span>
    </div>
  );
}

/** 来源新鲜度：按检索时间距今判断（<7d 新鲜 / <30d 一般 / 更久 陈旧）。 */
export function freshnessTone(iso: string | null): { label: string; dot: string } {
  if (!iso) return { label: "未知", dot: "bg-muted" };
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return { label: "未知", dot: "bg-muted" };
  const days = (Date.now() - then) / 86_400_000;
  if (days < 7) return { label: "新鲜", dot: "bg-state-success" };
  if (days < 30) return { label: "一般", dot: "bg-state-warning" };
  return { label: "陈旧", dot: "bg-state-error" };
}

export function FreshnessDot({ iso }: { iso: string | null }) {
  const { label, dot } = freshnessTone(iso);
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title={`来源新鲜度：${label}`}>
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} aria-hidden="true" />
      {label}
    </span>
  );
}
