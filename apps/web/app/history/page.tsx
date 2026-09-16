"use client";

/**
 * 研究历史（m10 §26.3）。任务列表 + 状态/公司/日期筛选 + 分页（≤10/页）+ 查看结果跳转。
 * 数据经 api.tasks.list（GET /api/v1/tasks?kind=research）读取，客户端做筛选与分页。
 *
 * 重构：筛选控件改用 Input/Select 原子组件，表格改用 Table，分页按钮用 Button（原为
 * 手写 `rounded-md border border-input p-1.5`），空态区分「无数据」与「无匹配」。
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, History, Search } from "lucide-react";
import { TaskStatus } from "@/components/research/status";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { StateView } from "@/components/ui/state-view";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ROUTES, TASK_STATUSES } from "@/lib/constants/api";
import { api } from "@/lib/api/client";
import type { TaskSummaryDto } from "@/lib/api/types";

const PAGE_SIZE = 10;

type HistRow = {
  taskId: string;
  query: string;
  company: string;
  status: (typeof TASK_STATUSES)[number];
  date: string;
  durationSec: number | null;
};

function fmtDateOnly(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function HistoryPage() {
  const [status, setStatus] = useState<string>("ALL");
  const [keyword, setKeyword] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tasks", "history", { kind: "research" }],
    queryFn: async () => {
      // P2：改用服务端分页，limit 传真实页大小，返回 total 用于分页。
      const res = await api.tasks.list({ kind: "research", limit: PAGE_SIZE });
      if (!res.ok) throw new Error(res.error.userMessage);
      return {
        items: res.data.items as TaskSummaryDto[],
        total: res.data.total,
      };
    },
  });

  const rows: HistRow[] = useMemo(
    () =>
      (data?.items ?? []).map((t) => ({
        taskId: t.task_id,
        query: t.query ?? "—",
        company: t.company ?? "—",
        status: t.status,
        date: fmtDateOnly(t.created_at),
        // P2：耗时来自后端实际起止时间（不再恒 "—"）。
        durationSec: typeof t.duration_sec === "number" ? t.duration_sec : null,
      })),
    [data],
  );

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return rows.filter((r) => {
      const matchStatus = status === "ALL" || r.status === status;
      const matchKw =
        !kw ||
        r.query.toLowerCase().includes(kw) ||
        r.company.toLowerCase().includes(kw) ||
        r.taskId.toLowerCase().includes(kw);
      const matchFrom = !dateFrom || r.date.replace(/-/g, "") >= dateFrom.replace(/-/g, "");
      const matchTo = !dateTo || r.date.replace(/-/g, "") <= dateTo.replace(/-/g, "");
      return matchStatus && matchKw && matchFrom && matchTo;
    });
  }, [rows, status, keyword, dateFrom, dateTo]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  // 走查发现：原实现把「一条任务都没有」和「筛选后无结果」都显示成同一句，
  // 后者不告知用户如何恢复。此处区分两种语义。
  const hasAnyRow = rows.length > 0;
  const hasNoMatch = hasAnyRow && filtered.length === 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">研究历史</h1>
        <p className="text-sm text-muted-foreground">按状态、公司、日期筛选历史任务；点击可跳转查看结果。</p>
      </header>

      {isError ? (
        <Alert variant="error" title="加载失败" description={(error as Error).message} />
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          leadingIcon={<Search />}
          value={keyword}
          onChange={(e) => { setKeyword(e.target.value); setPage(1); }}
          placeholder="搜索主题 / 公司 / 任务 ID…"
          aria-label="搜索历史任务"
          className="max-w-sm"
        />
        <label className="sr-only" htmlFor="hist-status">状态筛选</label>
        <Select
          id="hist-status"
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1); }}
          className="w-36"
          aria-label="状态筛选"
        >
          <option value="ALL">全部状态</option>
          {TASK_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <label className="sr-only" htmlFor="hist-from">起始日期</label>
        <Input
          id="hist-from"
          type="date"
          value={dateFrom}
          onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
          aria-label="起始日期"
          className="w-40"
        />
        <span className="text-muted-foreground">–</span>
        <label className="sr-only" htmlFor="hist-to">结束日期</label>
        <Input
          id="hist-to"
          type="date"
          value={dateTo}
          onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
          aria-label="结束日期"
          className="w-40"
        />
        <span className="text-xs text-muted-foreground tabular">{filtered.length} 条</span>
      </div>

      {isLoading ? (
        <StateView variant="loading" icon={History} title="加载研究历史中…" />
      ) : !hasAnyRow ? (
        <StateView
          icon={History}
          title="暂无研究任务"
          description="在「研究」页发起一次研究后，任务会出现在这里。"
        />
      ) : hasNoMatch ? (
        <StateView
          icon={Search}
          title="没有匹配的研究任务"
          description="放宽关键词、状态或日期范围试试。"
        />
      ) : (
        <>
          <Table>
            <TableHeader>
              <tr>
                <TableHead>任务 ID</TableHead>
                <TableHead>研究主题</TableHead>
                <TableHead>公司</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>日期</TableHead>
                <TableHead className="text-right">耗时</TableHead>
                <TableHead aria-label="操作" />
              </tr>
            </TableHeader>
            <TableBody>
              {pageRows.map((r) => (
                <TableRow key={r.taskId}>
                  <TableCell className="font-mono text-xs text-muted-foreground">{r.taskId}</TableCell>
                  <TableCell className="max-w-md truncate">{r.query}</TableCell>
                  <TableCell className="text-muted-foreground">{r.company}</TableCell>
                  <TableCell><TaskStatus status={r.status} /></TableCell>
                  <TableCell className="tabular text-muted-foreground">{r.date}</TableCell>
                  <TableCell className="text-right tabular">
                    {r.durationSec != null ? `${(r.durationSec / 60).toFixed(1)}min` : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    {r.status === "completed" ? (
                      <Link
                        href={ROUTES.researchResult(r.taskId)}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        查看结果 →
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground tabular">
              第 {safePage} / {totalPages} 页 · 每页 {PAGE_SIZE} 条
            </p>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="px-2"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                aria-label="上一页"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </Button>
              <span className="px-2 text-sm tabular">{safePage} / {totalPages}</span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="px-2"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                aria-label="下一页"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
