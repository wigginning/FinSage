"use client";

/**
 * 研究列表 / 新研究（m10 §26.3）。
 * 包含 ResearchComposer；提交后导航至结果页。近期任务经 api.tasks.list
 * （GET /api/v1/tasks?kind=research）读取，客户端取最近若干条。
 *
 * 重构：表格改用 Table 原子组件，错误/加载/空态改用 Alert + StateView（原为裸红字与灰字）。
 */
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { FlaskConical, Loader2 } from "lucide-react";
import { TaskStatus } from "@/components/research/status";
import { ResearchComposer } from "@/components/research/research-composer";
import { Alert } from "@/components/ui/alert";
import { StateView } from "@/components/ui/state-view";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ROUTES } from "@/lib/constants/api";
import { api } from "@/lib/api/client";
import type { TaskSummaryDto } from "@/lib/api/types";

const RECENT_LIMIT = 5;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ResearchPage() {
  const router = useRouter();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tasks", "recent", { kind: "research", limit: RECENT_LIMIT }],
    queryFn: async () => {
      const res = await api.tasks.list({ kind: "research", limit: RECENT_LIMIT });
      if (!res.ok) throw new Error(res.error.userMessage);
      return res.data.items as TaskSummaryDto[];
    },
  });

  const recent = data ?? [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">研究</h1>
        <p className="text-sm text-muted-foreground">创建新的研究工作台，或查看最近任务。</p>
      </header>

      <section aria-labelledby="new-research-heading">
        <h2 id="new-research-heading" className="mb-2 text-base font-semibold">
          发起新研究
        </h2>
        <ResearchComposer
          onSubmitted={(task) => router.push(ROUTES.researchResult(task.taskId))}
        />
      </section>

      <section className="space-y-2" aria-labelledby="recent-heading">
        <h2 id="recent-heading" className="text-base font-semibold">
          最近研究任务
        </h2>
        {isError ? (
          <Alert variant="error" title="加载失败" description={(error as Error).message} />
        ) : isLoading ? (
          <StateView
            variant="loading"
            icon={Loader2}
            title="加载最近任务中…"
            description="正在读取最近的研究任务。"
          />
        ) : recent.length === 0 ? (
          <StateView
            icon={FlaskConical}
            title="暂无研究任务"
            description="在上方填写研究主题并提交，即可开始一次完整研究。"
          />
        ) : (
          <Table>
            <TableHeader>
              <tr>
                <TableHead>主题</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>任务 ID</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead aria-label="操作" />
              </tr>
            </TableHeader>
            <TableBody>
              {recent.map((t) => (
                <TableRow key={t.task_id}>
                  <TableCell className="max-w-md truncate">{t.query ?? "—"}</TableCell>
                  <TableCell>
                    <TaskStatus status={t.status} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{t.task_id}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{fmtDate(t.created_at)}</TableCell>
                  <TableCell className="text-right">
                    {t.status === "completed" ? (
                      <Link
                        href={ROUTES.researchResult(t.task_id)}
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
        )}
      </section>
    </div>
  );
}
