"use client";

/**
 * EvidenceCard（m10 T1009 / §26.10）。
 * 展示 source / authority / page / section / excerpt / published & retrieved。
 * 支持 open（安全外链）、copy citation、select。
 */
import { useState } from "react";
import { Check, Copy, ExternalLink, FileText } from "lucide-react";
import type { EvidenceViewModel } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { FreshnessDot, ScoreBar } from "./score-bar";

/** P2 安全外链：仅允许 http/https 协议，阻断 javascript:/data: 等执行面（审计 §2.1）。
 * 外部来源 URL 是不可信输入（AGENTS.md §7）。 */
function safeSourceUrl(url: string | undefined | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
    return null;
  } catch {
    return null;
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function toCitation(evidence: EvidenceViewModel): string {
  const parts = [evidence.source, evidence.title].filter(Boolean);
  const loc = [evidence.page != null ? `p.${evidence.page}` : null, evidence.section ? `§${evidence.section}` : null]
    .filter(Boolean)
    .join(", ");
  if (loc) parts.push(loc);
  if (evidence.publishedAt) parts.push(`发表于 ${fmtDate(evidence.publishedAt)}`);
  return parts.join(" · ");
}

export function EvidenceCard({
  evidence,
  selected,
  onSelect,
}: {
  evidence: EvidenceViewModel;
  selected?: boolean;
  onSelect?: (id: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copyCitation() {
    try {
      await navigator.clipboard.writeText(toCitation(evidence));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 剪贴板不可用时不打断交互。
    }
  }

  const rootClass = cn(
    "card-surface rounded-lg border bg-card p-4 transition-colors",
    selected ? "border-state-info ring-1 ring-state-info" : "border-border",
  );

  return (
    <article className={rootClass} aria-current={selected ? "true" : undefined}>
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h4 className="text-sm font-semibold">{evidence.title || evidence.source}</h4>
        </div>
        <FreshnessDot iso={evidence.retrievedAt} />
      </header>

      <div className="mt-3 space-y-1.5">
        <ScoreBar label="相关性" value={evidence.relevanceScore} />
        <ScoreBar label="权威度" value={evidence.authorityScore ?? 0} />
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <div>
          <dt className="inline text-muted-foreground/70">来源：</dt>
          <dd className="inline font-medium text-gold-600">{evidence.source || "—"}</dd>
        </div>
        <div>
          <dt className="inline text-muted-foreground/70">页码范围：</dt>
          <dd className="inline">{evidence.page != null ? `p.${evidence.page}` : "—"}</dd>
        </div>
        <div>
          <dt className="inline text-muted-foreground/70">章节：</dt>
          <dd className="inline">{evidence.section ?? "—"}</dd>
        </div>
        <div>
          <dt className="inline text-muted-foreground/70">发布于：</dt>
          <dd className="inline">{fmtDate(evidence.publishedAt)}</dd>
        </div>
        <div>
          <dt className="inline text-muted-foreground/70">检索于：</dt>
          <dd className="inline">{fmtDate(evidence.retrievedAt)}</dd>
        </div>
      </dl>

      <blockquote className="mt-3 border-l-2 border-primary/40 pl-3 text-sm leading-relaxed text-foreground/90">
        {evidence.excerpt}
      </blockquote>

      <footer className="mt-3 flex items-center gap-1.5">
        {onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(evidence.id)}
            className={cn(
              "rounded px-2 py-1 text-xs font-medium transition-colors",
              selected ? "bg-state-info text-primary-foreground" : "hover:bg-muted",
            )}
          >
            {selected ? "已选中" : "在答案中定位"}
          </button>
        ) : null}
        <button
          type="button"
          onClick={copyCitation}
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium hover:bg-muted"
        >
          {copied ? <Check className="h-3 w-3 text-state-success" aria-hidden="true" /> : <Copy className="h-3 w-3" aria-hidden="true" />}
          {copied ? "已复制引用" : "复制引用"}
        </button>
        {(() => {
          const safeUrl = safeSourceUrl(evidence.sourceUrl);
          return safeUrl ? (
            <a
              href={safeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium hover:bg-muted"
            >
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
              打开来源
            </a>
          ) : null;
        })()}
      </footer>
    </article>
  );
}