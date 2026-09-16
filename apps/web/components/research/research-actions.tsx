"use client";

/**
 * ResearchActions（m10 T1014 / §26.10）。
 * Retry/Abort 操作区。
 * - Retry：仅当 status 为「可恢复失败」（failed 且 errorRetryable === true）时显示。
 * - 业务拒绝/弃权（failed 且 non-retryable；或 aborted）不显示 Retry。
 * - queued/running/streaming/verifying 时显示 中止 按钮（P2：补上 verifying→aborted，
 *   见审计 §2.8；中止前二次确认防误触）。
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";

const ABORTABLE_STATES = new Set(["queued", "running", "streaming", "verifying"]);

export function ResearchActions({
  status,
  errorRetryable = false,
  onRetry,
  onAbort,
}: {
  status: string;
  errorRetryable?: boolean;
  onRetry?: () => void;
  onAbort?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const showRetry = status === "failed" && errorRetryable === true;
  const showAbort = ABORTABLE_STATES.has(status) && Boolean(onAbort);

  if (!showRetry && !showAbort) {
    return <span aria-hidden="true" />;
  }

  const handleAbortClick = () => {
    if (confirming) {
      setConfirming(false);
      onAbort?.();
    } else {
      setConfirming(true); // P2：中止前二次确认，防误触
    }
  };

  return (
    <div className="flex items-center gap-2" aria-label="研究任务操作">
      {showRetry ? (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          重试研究
        </Button>
      ) : null}
      {showAbort ? (
        <Button type="button" variant="danger" size="sm" onClick={handleAbortClick}>
          {confirming ? "确认中止？" : "中止"}
        </Button>
      ) : null}
    </div>
  );
}