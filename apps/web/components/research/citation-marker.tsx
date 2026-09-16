"use client";

/**
 * CitationMarker（m10 T1011 / §26.10）。
 * 答案正文内的引用小标记：金色/高亮，点击回调定位到对应证据（EvidenceCard 联动）。
 */
import { cn } from "@/lib/utils";

export function CitationMarker({
  marker,
  evidenceId,
  onClick,
}: {
  marker: string;
  evidenceId: string;
  onClick?: (evidenceId: string) => void;
}) {
  const className =
    "mx-0.5 inline-flex -translate-y-0.5 items-center rounded bg-state-warning-bg px-1 py-0 text-xs font-semibold text-state-warning ring-1 ring-inset ring-state-warning/30 transition-colors";
  const label = `引用标记 ${marker}，定位到证据`;

  if (!onClick) {
    return (
      <sup className={cn(className, "cursor-default")} aria-label={label} aria-hidden="false">
        {marker}
      </sup>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onClick(evidenceId)}
      aria-label={label}
      title={`定位到证据 ${evidenceId}`}
      className={cn(className, "align-top cursor-pointer hover:bg-state-warning hover:text-white focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none")}
    >
      {marker}
    </button>
  );
}