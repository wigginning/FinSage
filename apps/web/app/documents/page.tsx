"use client";

/**
 * 文档库列表（m10 §26.3）。上传经 api.documents.create（FormData）；列表经 api.documents.list
 * （GET /api/v1/documents）读取。后端摘要含 document_id/filename/size/created_at/chunk_count/
 * status/citation_count（§2.7 溯源统计）。组件禁止裸 fetch；API 一律经 api client。
 *
 * 重构：上传区用 Card 容器，提示条用 Alert（原为手写的 bg-state-*-bg 裸 <p>），
 * 列表用 Table 原子组件，状态标签用 Badge，加载/空态用 StateView。
 */
import { useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { FileText, UploadCloud } from "lucide-react";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

export default function DocumentsPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["documents", "list"],
    queryFn: async () => {
      const res = await api.documents.list({ limit: 200 });
      if (!res.ok) throw new Error(res.error.userMessage);
      return res.data.items as DocumentSummaryDto[];
    },
  });

  async function handleUpload() {
    const input = fileRef.current;
    const file = input?.files?.[0];
    if (!file) {
      setNotice({ kind: "err", text: "请先选择一个文件。" });
      return;
    }
    setUploading(true);
    setNotice(null);
    const formData = new FormData();
    formData.append("file", file);
    const result = await api.documents.create(formData);
    setUploading(false);
    if (!result.ok) {
      setNotice({ kind: "err", text: `上传失败：${result.error.userMessage}` });
      return;
    }
    if (input) input.value = "";
    setNotice({
      kind: "ok",
      text: `已提交文档（document_id = ${result.data.document_id}），后台将解析并分块索引。`,
    });
    void refetch();
  }

  const docs = data ?? [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">文档库</h1>
        <p className="text-sm text-muted-foreground">上传公开文档作为研究中证据来源；解析后按 chunk 分块检索。</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <UploadCloud className="h-4 w-4 text-primary" aria-hidden="true" />
            上传文档
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <input ref={fileRef} type="file" aria-label="选择要上传的文档" className="text-sm" />
            <Button variant="primary" size="md" loading={uploading} disabled={uploading} onClick={handleUpload}>
              上传并解析
            </Button>
          </div>
          {notice ? (
            <Alert
              className="mt-3"
              variant={notice.kind === "ok" ? "success" : "error"}
              description={notice.text}
              dismissible
            />
          ) : null}
        </CardContent>
      </Card>

      <section className="space-y-2" aria-labelledby="docs-heading">
        <h2 id="docs-heading" className="text-base font-semibold">
          已上传文档
          <span className="ml-2 text-xs font-normal text-muted-foreground">({docs.length})</span>
        </h2>

        {isError ? (
          <StateView
            variant="error"
            icon={FileText}
            title="文档列表加载失败"
            description={(error as Error).message}
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <tr>
                  <TableHead>文档</TableHead>
                  <TableHead className="text-right">大小</TableHead>
                  <TableHead className="text-right">分块</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>上传时间</TableHead>
                </tr>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <tr>
                    <td colSpan={5}>
                      <StateView
                        compact
                        variant="loading"
                        title="加载文档列表中…"
                      />
                    </td>
                  </tr>
                ) : docs.length === 0 ? (
                  <tr>
                    <td colSpan={5}>
                      <StateView
                        compact
                        icon={FileText}
                        title="尚未上传文档"
                        description="上传公开财报或研报后，研究结果即可带引用溯源。"
                      />
                    </td>
                  </tr>
                ) : (
                  docs.map((d) => (
                    <TableRow key={d.document_id}>
                      <TableCell>
                        <Link href={ROUTES.document(d.document_id)} className="group flex items-center gap-2">
                          <FileText className="h-4 w-4 text-primary" aria-hidden="true" />
                          <span className="font-medium group-hover:underline">{d.filename}</span>
                        </Link>
                        <span className="mt-0.5 block font-mono text-xs text-muted-foreground">{d.document_id}</span>
                      </TableCell>
                      <TableCell className="text-right tabular text-muted-foreground">{fmtBytes(d.size)}</TableCell>
                      <TableCell className="text-right tabular text-muted-foreground">{d.chunk_count}</TableCell>
                      <TableCell>
                        <Badge variant={d.status === "ingested" ? "success" : "neutral"} size="sm">
                          {d.status === "ingested" ? "已入库" : d.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="tabular text-muted-foreground">{fmtDate(d.created_at)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
            <p className="text-xs text-muted-foreground">分块数 / 状态 / 被引用次数由后端溯源统计提供。</p>
          </>
        )}
      </section>
    </div>
  );
}
