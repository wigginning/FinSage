"use client";

/**
 * 公司库列表（m10 §26.3 / ADR-0006）。数据经 api.companies.list
 * （GET /api/v1/companies）读取；搜索/市场筛选在客户端做。未就绪字段诚实为 null。
 *
 * 重构：走查发现 KPI/输入/表格/空态/徽章 5 处手写重复，本页用新原子组件统一替换。
 * 关键改进：空态文案区分"无数据"（api 没返回任何公司）与"无匹配"（被搜索/市场过滤后无结果）。
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Building2, Search, Building } from "lucide-react";
import { MARKETS, ROUTES } from "@/lib/constants/api";
import { api } from "@/lib/api/client";
import type { CompanySummaryDto } from "@/lib/api/types";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Tag } from "@/components/ui/tag";
import { StateView } from "@/components/ui/state-view";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toISOString().slice(0, 10);
}

function FreshnessBadge({ lastResearchedAt }: { lastResearchedAt: string | null }) {
  if (!lastResearchedAt) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const days = Math.floor(
    (Date.now() - new Date(lastResearchedAt).getTime()) / (24 * 3600 * 1000),
  );
  if (days <= 7) {
    return <Badge variant="success" size="sm">近 7 天已研究</Badge>;
  }
  return <Badge variant="warning" size="sm">来源已过期</Badge>;
}

export default function CompaniesPage() {
  const [keyword, setKeyword] = useState("");
  const [market, setMarket] = useState<string>("ALL");

  // §3.1 deferred enrichment：先秒回基础列表（enrich=false），再后台补行情/行业（enrich=true）。
  const basic = useQuery({
    queryKey: ["companies", "basic"],
    queryFn: async () => {
      const res = await api.companies.list({ limit: 200, enrich: false });
      if (!res.ok) throw new Error(res.error.userMessage);
      return res.data.items as CompanySummaryDto[];
    },
  });

  const enriched = useQuery({
    queryKey: ["companies", "enriched"],
    queryFn: async () => {
      const res = await api.companies.list({ limit: 200, enrich: true });
      if (!res.ok) throw new Error(res.error.userMessage);
      return res.data.items as CompanySummaryDto[];
    },
    enabled: basic.isSuccess,
  });

  const data = enriched.data ?? basic.data;
  const isError = basic.isError || enriched.isError;
  const error = basic.error ?? enriched.error;
  const enriching = basic.isSuccess && enriched.isLoading;

  const filtered = useMemo(
    () =>
      (data ?? []).filter((c) => {
        const kw = keyword.trim().toLowerCase();
        const matchKw = !kw || c.name.toLowerCase().includes(kw) || c.ticker.toLowerCase().includes(kw);
        const matchMarket = market === "ALL" || c.market === market;
        return matchKw && matchMarket;
      }),
    [data, keyword, market],
  );

  const hasAnyCompany = (data?.length ?? 0) > 0;
  const hasNoMatch = hasAnyCompany && filtered.length === 0;
  const isInitialLoading = basic.isLoading;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">公司库</h1>
        <p className="text-sm text-muted-foreground">按公司查看档案、财务摘要、研究历史与来源新鲜度。</p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          inputSize="md"
          leadingIcon={<Search />}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索公司名称或代码…"
          aria-label="搜索公司"
          className="max-w-sm"
        />
        <label className="sr-only" htmlFor="company-market">市场筛选</label>
        <Select
          id="company-market"
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="w-36"
          aria-label="市场筛选"
        >
          <option value="ALL">全部市场</option>
          {MARKETS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </Select>
        <span className="text-xs text-muted-foreground tabular">{filtered.length} 家</span>
        {enriching ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gold-500" aria-hidden="true" />
            正在补充行情…
          </span>
        ) : null}
      </div>

      {isError ? (
        <Alert
          variant="error"
          title="加载失败"
          description={(error as Error).message}
        />
      ) : isInitialLoading ? (
        <StateView
          icon={Building}
          title="加载公司库中…"
          description="正在拉取已研究公司与基础行情。"
        />
      ) : !hasAnyCompany ? (
        <StateView
          icon={Building}
          title="公司库暂无数据"
          description="尚未收录任何公司。研究完成后，公司会随任务结果自动入库。"
        />
      ) : hasNoMatch ? (
        <StateView
          icon={Search}
          title="没有匹配的公司"
          description="换一个关键词或市场试试。"
        />
      ) : (
        <Table>
          <TableHeader>
            <tr>
              <TableHead>公司</TableHead>
              <TableHead>市场</TableHead>
              <TableHead>行业</TableHead>
              <TableHead className="text-right">现价</TableHead>
              <TableHead className="text-center">研究次数</TableHead>
              <TableHead>最近研究</TableHead>
              <TableHead>来源新鲜度</TableHead>
            </tr>
          </TableHeader>
          <TableBody>
            {filtered.map((c) => (
              <TableRow key={c.ticker}>
                <TableCell>
                  <Link href={ROUTES.company(c.ticker)} className="group flex items-center gap-2">
                    <Building2 className="h-4 w-4 text-primary" aria-hidden="true" />
                    <span className="font-medium group-hover:underline">{c.name}</span>
                    <span className="font-mono text-xs text-muted-foreground">{c.ticker}</span>
                  </Link>
                </TableCell>
                <TableCell><Tag>{c.market}</Tag></TableCell>
                <TableCell className="text-muted-foreground">{c.industry ?? "—"}</TableCell>
                <TableCell className="text-right tabular">{c.price ?? "—"}</TableCell>
                <TableCell className="text-center tabular">{c.research_count}</TableCell>
                <TableCell className="tabular text-muted-foreground">{fmtDate(c.last_researched_at)}</TableCell>
                <TableCell><FreshnessBadge lastResearchedAt={c.last_researched_at} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
