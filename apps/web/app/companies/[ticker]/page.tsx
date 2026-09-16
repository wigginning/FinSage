"use client";

/**
 * 公司详情（m10 §26.3 / ADR-0006）。数据经 api.companies.get
 * （GET /api/v1/companies/{ticker}）读取：profile / 财务摘要 / 近期任务 / 来源新鲜度。
 * 未就绪字段诚实为 null/空，不展示演示占位数字。
 *
 * 重构：走查发现 404 态简陋，本页用 StateView 替换裸错误条；卡片容器用 Card 统一。
 */
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, Building2, FileSearch, Globe2 } from "lucide-react";
import { TaskStatus } from "@/components/research/status";
import { ROUTES } from "@/lib/constants/api";
import { api } from "@/lib/api/client";
import type { CompanyDetailDto } from "@/lib/api/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import { StateView } from "@/components/ui/state-view";
import { buttonClasses } from "@/components/ui/button";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toISOString().slice(0, 10);
}

/** 财务指标 key → 中文标签（§2.4 财务摘要展示）。 */
const FINANCIAL_LABELS: Record<string, string> = {
  revenue: "营业总收入",
  net_income: "归母净利润",
  gross_margin: "毛利率",
  net_margin: "销售净利率",
  roe: "净资产收益率(ROE)",
  debt_ratio: "资产负债率",
  revenue_growth: "营收增长率",
};

function financialLabel(metric: string): string {
  return FINANCIAL_LABELS[metric] ?? metric;
}

export default function CompanyDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = params.ticker;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["companies", "detail", ticker],
    queryFn: async () => {
      const res = await api.companies.get(ticker);
      if (!res.ok) {
        // 保留 code：FIN-1004=资源不存在，UI 据此降级为中性「未收录」空态而非红色错误态。
        const err = new Error(res.error.userMessage);
        (err as Error & { code?: string }).code = res.error.code;
        throw err;
      }
      return res.data as CompanyDetailDto;
    },
    enabled: Boolean(ticker),
  });

  if (isLoading) {
    return (
      <StateView
        icon={Building2}
        title={`加载 ${ticker} 的公司档案中…`}
        description="正在拉取财务摘要、研究历史与来源新鲜度。"
      />
    );
  }

  if (isError || !data) {
    const code = (error as Error & { code?: string }).code;
    const notFound = code === "FIN-1004";
    return (
      <StateView
        variant={notFound ? "empty" : "error"}
        icon={Building2}
        title={notFound ? "暂未收录该公司" : "公司加载失败"}
        description={
          notFound
            ? "该股票代码可能尚未被研究收录。返回公司库，看看已收录的公司。"
            : isError
              ? (error as Error).message
              : "该股票可能尚未收录。"
        }
        action={
          <Link href={ROUTES.companies} className={buttonClasses("outline", "sm")}>
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            返回公司库
          </Link>
        }
      />
    );
  }

  const c = data;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={ROUTES.companies}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          返回公司库
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Building2 className="h-6 w-6" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-semibold tracking-tight">{c.name}</h1>
                <span className="font-mono text-sm text-muted-foreground">{c.ticker}</span>
                <Tag>{c.market}</Tag>
                {c.price ? <span className="text-sm tabular text-muted-foreground">现价 {c.price}</span> : null}
              </div>
              <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                <Globe2 className="h-3.5 w-3.5" aria-hidden="true" />
                {[c.industry, c.sector, c.exchange].filter(Boolean).join(" · ") || "行业信息待 Provider 提供"}
              </p>
              {c.description ? <p className="mt-1 text-xs text-muted-foreground">{c.description}</p> : null}
            </div>
          </div>
        </CardHeader>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>财务摘要</CardTitle>
            <CardDescription>最近一期关键指标</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {c.financials.length === 0 ? (
              <StateView
                compact
                icon={BarChart3}
                title="暂无财务指标"
                description="待 Provider 提供后自动填充。"
              />
            ) : (
              <dl className="divide-y divide-border">
                {c.financials.map((m) => (
                  <div key={m.metric} className="flex items-center justify-between px-4 py-3">
                    <dt className="text-sm text-muted-foreground">{financialLabel(m.metric)}</dt>
                    <dd className="tabular text-sm font-medium">
                      {m.value}
                      {m.unit ? ` ${m.unit}` : ""}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>近期研究任务</CardTitle>
            <CardDescription>与该公司相关的最近研究</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {c.recent_tasks.length === 0 ? (
              <StateView
                compact
                icon={FileSearch}
                title="暂无研究任务"
                description="针对该公司发起研究后，任务会出现在这里。"
              />
            ) : (
              <ul className="divide-y divide-border">
                {c.recent_tasks.map((t) => (
                  <li key={t.task_id} className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Link
                        href={ROUTES.researchResult(t.task_id)}
                        className="font-mono text-xs text-primary hover:underline"
                      >
                        {t.task_id}
                      </Link>
                      <TaskStatus status={t.status} />
                      <span className="ml-auto text-xs text-muted-foreground tabular">{fmtDate(t.created_at)}</span>
                    </div>
                    <p className="mt-1 truncate text-sm">{t.query ?? "—"}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>来源新鲜度</CardTitle>
            <CardDescription>档案与引用数据的更新频度</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border text-sm">
              <li className="flex items-center gap-2 px-4 py-3">
                <span className="h-2 w-2 rounded-full bg-state-success" aria-hidden="true" />
                <span>最近研究：{fmtDate(c.last_researched_at)}</span>
              </li>
              <li className="flex items-center gap-2 px-4 py-3">
                <span className="h-2 w-2 rounded-full bg-state-warning" aria-hidden="true" />
                <span>数据源：{c.source ?? "未装配"}</span>
              </li>
              <li className="flex items-center gap-2 px-4 py-3">
                <span className="h-2 w-2 rounded-full bg-state-warning" aria-hidden="true" />
                <span>数据获取：{fmtDate(c.retrieved_at)}</span>
              </li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
