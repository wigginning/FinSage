"use client";

/**
 * CalculationCard（m10 T1010 / §26.10）。
 * 展示 metric（name）/ formula / inputs / result / unit / currency / period / sources。
 * 可复现计算用 icon 标注；sourceEvidenceIds 关联证据链。
 */
import { Calculator } from "lucide-react";
import type { CalculationViewModel } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export function CalculationCard({
  calc,
  selected,
  onSelect,
}: {
  calc: CalculationViewModel;
  selected?: boolean;
  onSelect?: (id: string) => void;
}) {
  const unit = [calc.currency, calc.unit].filter(Boolean).join("");

  return (
    <article
      className={cn(
        "card-surface rounded-lg border bg-card p-4 transition-colors",
        selected ? "border-state-info ring-1 ring-state-info" : "border-border",
      )}
      aria-current={selected ? "true" : undefined}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Calculator className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h4 className="text-sm font-semibold">{calc.name}</h4>
        </div>
        <span className="text-xs text-muted-foreground">{calc.reproducible ? "可复现计算" : "估算结果"}</span>
      </header>

      <p className="mt-2 font-mono text-xs text-muted-foreground">{calc.formula}</p>

      {calc.inputs.length > 0 ? (
        <dl className="mt-3 space-y-1 text-xs">
          {calc.inputs.map((input) => (
            <div key={input.name} className="flex justify-between gap-3">
              <dt className="text-muted-foreground">{input.name}</dt>
              <dd className="tabular">{input.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <p className="mt-3 flex items-baseline justify-between border-t border-border pt-2">
        <span className="text-xs text-muted-foreground">结果</span>
        <span className="tabular text-lg font-semibold">
          {calc.result}
          {unit ? <span className="ml-1 text-sm text-muted-foreground">{unit}</span> : null}
        </span>
      </p>

      {calc.period ? <p className="mt-1 text-xs text-muted-foreground">报告期：{calc.period}</p> : null}

      <footer className="mt-2 flex items-center justify-between gap-2">
        <div>
          <span className="text-xs text-muted-foreground">来源证据：</span>
          <span className="text-xs tabular text-muted-foreground">{calc.sourceEvidenceIds.length} 条</span>
        </div>
        {onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(calc.id)}
            className={cn(
              "rounded px-2 py-1 text-xs font-medium transition-colors",
              selected ? "bg-state-info text-primary-foreground" : "hover:bg-muted",
            )}
          >
            {selected ? "已选中" : "定位证据"}
          </button>
        ) : null}
      </footer>
    </article>
  );
}