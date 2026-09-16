"use client";

/**
 * 研究结果页（m10 / §26.3、§26.9）。
 * 用 useParams 取 taskId；以 Zustand store 承接状态；链接 SSE 流消费事件。
 * taskId 变化时先 reset() 再 startTask()；No-Guess 经 console.warn 上报。
 */
import { useCallback, useEffect, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useShallow } from "zustand/react/shallow";
import { ArrowLeft, ArrowUpRight, FileSearch } from "lucide-react";
import { useResearchStore } from "@/lib/research/research-store";
import { applySSEEvent } from "@/lib/research/sse-handler";
import { SseClient } from "@/lib/research/sse-client";
import { api } from "@/lib/api/client";
import { ROUTES, SSE_BASE_URL } from "@/lib/constants/api";
import { ResearchAnswer } from "@/components/research/research-answer";
import { ResearchTrace } from "@/components/research/research-trace";
import { ResearchActions } from "@/components/research/research-actions";
import { StatusBadge, ErrorState } from "@/components/research/status";
import { Card, CardContent } from "@/components/ui/card";
import { StateView } from "@/components/ui/state-view";
import { buttonClasses } from "@/components/ui/button";

const ACTIVE_STATES = new Set(["submitting", "queued", "running", "streaming", "verifying", "idle"]);

export default function ResearchResultPage() {
  const params = useParams<{ taskId: string }>();
  const taskId = params.taskId;

  const {
    status,
    progress,
    answer,
    traceEvents,
    selectedEvidenceId,
    selectedCalculationId,
    error,
    selectEvidence,
    selectCalculation,
  } = useResearchStore(
    useShallow((s) => ({
      status: s.status,
      progress: s.progress,
      answer: s.answer,
      traceEvents: s.traceEvents,
      selectedEvidenceId: s.selectedEvidenceId,
      selectedCalculationId: s.selectedCalculationId,
      error: s.error,
      selectEvidence: s.selectEvidence,
      selectCalculation: s.selectCalculation,
    })),
  );

  const sseRef = useRef<SseClient | null>(null);

  const restart = useCallback((id: string): void => {
    const store = useResearchStore.getState();
    store.reset();
    store.startTask(id, "");
    sseRef.current?.close();
    const client = new SseClient(
      api.getToken(),
      {
        onEvent: (envelope) =>
          applySSEEvent(envelope, useResearchStore.getState(), (raw) =>
            console.warn("[no-guess]", raw),
          ),
        onUnknownEvent: (raw) => console.warn("[no-guess]", raw),
        onError: (err) => {
          // P1 修复：SSE 连接失败必须对用户可见，而非仅 console.warn。
          console.warn("[sse-error]", err.message);
          const state = useResearchStore.getState();
          if (!state.answer && state.status !== "completed" && state.status !== "failed") {
            // SSE 客户端在 4xx 时把后端 FIN 错误码（如 FIN-1004=资源不存在）挂到 err 上；
            // 命中 FIN-1004 时降级为中性「未找到该研究任务」空态（与 company/document 详情一致）。
            const code = (err as Error & { code?: string }).code;
            const notFound = code === "FIN-1004";
            state.setError({
              code: code ?? "SSE_DISCONNECTED",
              message: err.message || "SSE 连接中断",
              userMessage: notFound
                ? "该任务可能已过期或不存在。"
                : (err as Error & { userMessage?: string }).userMessage ||
                  "实时连接中断，结果可能不完整。请稍后刷新重试。",
              traceId: state.activeTraceId ?? "",
              retryable: !notFound,
            });
          }
        },
      },
      `${SSE_BASE_URL}/tasks/${encodeURIComponent(id)}/stream`,
    );
    sseRef.current = client;
    void client.connect();
  }, []);

  useEffect(() => {
    if (!taskId) return;
    restart(taskId);
    return () => {
      sseRef.current?.close();
      sseRef.current = null;
    };
  }, [taskId, restart]);

  const handleAbort = useCallback(async () => {
    // §1.3 真实中止：先调后端取消任务（发 task.aborted），再关流。
    // 若任务已终结（如 DevRunner 瞬时完成），后端幂等返回当前状态，不强制置 aborted。
    const res = await api.tasks.abort(taskId);
    sseRef.current?.close();
    if (res.ok && res.data.status === "aborted") {
      useResearchStore.getState().setStatus("aborted");
    }
  }, [taskId]);

  const handleSelect = useCallback(
    (kind: "evidence" | "calculation", targetId: string): void => {
      if (kind === "evidence") selectEvidence(targetId);
      else selectCalculation(targetId);
    },
    [selectEvidence, selectCalculation],
  );

  const showProgress = ACTIVE_STATES.has(status) && progress >= 0;
  const showAnswer = Boolean(answer && answer.answer.trim());

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">研究结果</h1>
        <StatusBadge status={status} />
        <div className="ml-auto min-w-0">
          <ResearchActions
            status={status}
            errorRetryable={error?.retryable === true}
            onRetry={() => restart(taskId)}
            onAbort={handleAbort}
          />
        </div>
      </header>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-sm">
            <ArrowUpRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="truncate font-mono">{taskId}</span>
          </div>
          {showProgress ? (
            <div className="mt-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.round(progress * 100)}%` }}
                />
              </div>
              <p className="mt-1 text-right text-xs tabular text-muted-foreground">
                {status === "verifying" ? "交叉验证中" : status === "streaming" ? "流式生成中" : Math.round(progress * 100)}%
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {error ? (
        error.code === "FIN-1004" ? (
          <StateView
            variant="empty"
            icon={FileSearch}
            title="未找到该研究任务"
            description="该任务可能已过期或不存在。返回研究工作台，发起新的研究。"
            action={
              <Link href={ROUTES.research} className={buttonClasses("outline", "sm")}>
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                返回研究工作台
              </Link>
            }
          />
        ) : (
          <ErrorState userMessage={error.userMessage || error.message} traceId={error.traceId} />
        )
      ) : null}

      {showAnswer && answer ? (
        <ResearchAnswer
          answer={answer}
          onSelect={handleSelect}
          selectedEvidenceId={selectedEvidenceId}
          selectedCalculationId={selectedCalculationId}
        />
      ) : null}

      <section className="space-y-2" aria-labelledby="trace-heading">
        <h2 id="trace-heading" className="text-base font-semibold">
          执行链路
        </h2>
        <ResearchTrace events={traceEvents} />
      </section>
    </div>
  );
}