"use client";

/**
 * 文档详情（m10 §26.3）。展示文档元数据。
 * 数据经 api.documents.get（GET /api/v1/documents/{document_id}）读取。
 * 后端摘要含 document_id/filename/size/created_at/chunk_count/status/citation_count。
 * 组件禁止裸 fetch；API 一律经 api client。
 *
 * 重构：加载/错误态用 StateView（原为卡片里一行裸文字），容器用 Card，状态用 Badge。
 */
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StateView } from "@/components/ui/state-view";
import { ROUTES } from "@/lib/constants/api";
import { api } from "@/lib/api/client";
import type { DocumentSummaryDto } from "@/lib/api/types";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const kb = n / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toISOString().slice(0, 10);
}

export default function DocumentDetailPage() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["documents", "detail", documentId],
    queryFn: async () => {
      const res = await api.documents.get(documentId);
      if (!res.ok) {
        const err = new Error(res.error.userMessage);
        (err as Error & { code?: string }).code = res.error.code;
        throw err;
      }
      return res.data as DocumentSummaryDto;
    },
    enabled: Boolean(documentId),
  });

  if (isLoading) {
    return (
      <StateView
        variant="loading"
        icon={FileText}
        title="加载文档详情中…"
        description="正在读取文档元数据与溯源统计。"
      />
    );
  }

  if (isError || !data) {
    const code = (error as Error & { code?: string }).code;
    const notFound = code === "FIN-1004";
    return (
      <StateView
        variant={notFound ? "empty" : "error"}
        icon={FileText}
        title={notFound ? "暂无该文档" : "文档加载失败"}
        description={
          notFound
            ? "该文档可能已被删除或尚未入库。返回文档库，看看已上传的文档。"
            : isError
              ? (error as Error).message
              : "该文档可能已被删除。"
        }
        action={
          <Link href={ROUTES.documents} className={buttonClasses("outline", "sm")}>
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            返回文档库
          </Link>
        }
      />
    );
  }

  const meta: Array<{ label: string; value: React.ReactNode }> = [
    { label: "文档 ID", value: <span className="font-mono text-xs">{data.document_id}</span> },
    { label: "文件名", value: data.filename },
    { label: "大小", value: <span className="tabular">{fmtBytes(data.size)}</span> },
    { label: "分块数", value: <span className="tabular">{data.chunk_count}</span> },
    {
      label: "状态",
      value: (
        <Badge variant={data.status === "ingested" ? "success" : "neutral"} size="sm">
          {data.status === "ingested" ? "已入库" : data.status}
        </Badge>
      ),
    },
    { label: "被引用次数", value: <span className="tabular">{data.citation_count}</span> },
    { label: "上传时间", value: <span className="tabular">{fmtDate(data.created_at)}</span> },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <FileText className="h-6 w-6" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-2xl font-semibold tracking-tight">{data.filename}</h1>
              <p className="mt-1 font-mono text-sm text-muted-foreground">{data.document_id}</p>
            </div>
          </div>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>文档元数据</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            {meta.map((m) => (
              <div key={m.label} className="flex justify-between gap-3 border-b border-border py-2">
                <dt className="text-muted-foreground">{m.label}</dt>
                <dd>{m.value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-muted-foreground">
            分块数 / 被引用次数由后端溯源统计提供。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
