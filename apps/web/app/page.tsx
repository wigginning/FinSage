"use client";

/**
 * 研究工作台首页（m10 §26.3）。由于提交后需导航到结果页（useRouter），为 client 组件。
 * 统计卡经 api 读取真实计数（公司数 / 任务数）；无数据源的指标诚实显示 "—"，
 * 不展示伪造数字（AGENTS.md §10）。
 */
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, FileSearch, ShieldCheck, TrendingUp } from "lucide-react";
import { ResearchComposer } from "@/components/research/research-composer";
import { TaskStatus } from "@/components/research/status";
import { KPIStat } from "@/components/ui/kpi-stat";
import { ROUTES } from "@/lib/constants/api";
import { api } from "@/lib/api/client";

export default function HomePage() {
  const router = useRouter();

  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: async () => {
      const res = await api.stats.get();
      if (!res.ok) throw new Error(res.error.userMessage);
      return res.data;
    },
  });

  const s = stats.data;
  // P2：统计失败时显示 "—"（诚实空态），而非静默显示误导性的 0（审计 §2.8）。
  const statValue = (n: number | undefined): string => {
    if (stats.isLoading) return "…";
    if (stats.isError) return "—";
    return String(n ?? 0);
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">研究工作台</h1>
        <p className="text-sm text-muted-foreground">
          证据优先 · 确定性金融 · 可审计研究。提交研究主题，系统将检索证据、执行财务计算并交叉验证。
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPIStat
          icon={FileSearch}
          label="已研究公司"
          value={statValue(s?.companies_count)}
          sub="覆盖 CN / US / HK / GLOBAL 市场"
        />
        <KPIStat
          icon={ClipboardList}
          label="研究任务"
          value={statValue(s?.tasks_count)}
          sub="含排队 / 运行 / 已完成"
        />
        <KPIStat
          icon={TrendingUp}
          label="可复现计算"
          value={statValue(s?.calculations_count)}
          sub="全部经确定性 Python 执行"
        />
        <KPIStat
          icon={ShieldCheck}
          label="证据引用"
          value={statValue(s?.evidence_count)}
          sub="每条均归档至来源 chunk"
        />
      </div>

      <section aria-labelledby="new-research-heading">
        <div className="mb-2 flex items-center justify-between">
          <h2 id="new-research-heading" className="text-base font-semibold">
            发起新研究
          </h2>
          <TaskStatus status="idle" />
        </div>
        <ResearchComposer
          onSubmitted={(task) => router.push(ROUTES.researchResult(task.taskId))}
        />
      </section>
    </div>
  );
}
