"use client";

/**
 * 全局搜索（§2.1）：顶栏聚合搜索公司 / 文档 / 研究任务。
 * 输入防抖后并行调 companies/documents/tasks 的 keyword 搜索，下拉分组展示，
 * 点击或回车导航到对应详情页。
 */
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, FileText, History, Search } from "lucide-react";
import { api } from "@/lib/api/client";
import { ROUTES } from "@/lib/constants/api";
import type { CompanySummaryDto, DocumentSummaryDto, TaskSummaryDto } from "@/lib/api/types";
import { Input } from "@/components/ui/input";

interface Group {
  key: string;
  label: string;
  icon: typeof Building2;
  items: { id: string; title: string; sub: string; href: string }[];
}

const DEBOUNCE_MS = 300;

export function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [groups, setGroups] = useState<Group[]>([]);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setGroups([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const [companies, documents, tasks] = await Promise.all([
          api.companies.list({ keyword: q, limit: 5 }),
          api.documents.list({ keyword: q, limit: 5 }),
          api.tasks.list({ keyword: q, limit: 5 }),
        ]);
        const next: Group[] = [];
        if (companies.ok && companies.data.items.length) {
          next.push({
            key: "companies",
            label: "公司",
            icon: Building2,
            items: (companies.data.items as CompanySummaryDto[]).map((c) => ({
              id: c.ticker,
              title: c.name,
              sub: `${c.ticker} · ${c.market}`,
              href: ROUTES.company(c.ticker),
            })),
          });
        }
        if (documents.ok && documents.data.items.length) {
          next.push({
            key: "documents",
            label: "文档",
            icon: FileText,
            items: (documents.data.items as DocumentSummaryDto[]).map((d) => ({
              id: d.document_id,
              title: d.filename,
              sub: `${d.chunk_count} 分块`,
              href: ROUTES.document(d.document_id),
            })),
          });
        }
        if (tasks.ok && tasks.data.items.length) {
          next.push({
            key: "tasks",
            label: "研究任务",
            icon: History,
            items: (tasks.data.items as TaskSummaryDto[]).map((t) => ({
              id: t.task_id,
              title: t.query || t.company || t.task_id,
              sub: `${t.status} · ${t.task_id.slice(0, 8)}`,
              href: ROUTES.researchResult(t.task_id),
            })),
          });
        }
        setGroups(next);
        setOpen(true);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(href);
  }

  const total = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <div ref={boxRef} className="relative">
      <Input
        type="search"
        inputSize="md"
        leadingIcon={<Search />}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => query.trim() && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && groups.length && groups[0].items.length) {
            go(groups[0].items[0].href);
          }
        }}
        placeholder="搜索公司、文档、研究任务…"
        aria-label="全局搜索"
        className="bg-muted"
      />
      {open && query.trim() ? (
        <div className="absolute left-0 right-0 top-11 z-50 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          {loading ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">搜索中…</p>
          ) : total === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">未找到匹配结果。</p>
          ) : (
            groups.map((g) => (
              <div key={g.key} className="border-b border-border last:border-b-0">
                <p className="flex items-center gap-1.5 px-4 pt-2.5 pb-1 text-xs font-semibold text-muted-foreground">
                  <g.icon className="h-3.5 w-3.5" aria-hidden="true" />
                  {g.label}
                </p>
                {g.items.map((it) => (
                  <button
                    key={it.id}
                    type="button"
                    onClick={() => go(it.href)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm hover:bg-muted"
                  >
                    <span className="truncate font-medium">{it.title}</span>
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{it.sub}</span>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
