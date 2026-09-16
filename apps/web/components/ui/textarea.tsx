"use client";

/**
 * Textarea — 多行输入（替代 composer 中的 `w-full resize-none rounded-md border border-input ...`）。
 */
import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, error, rows = 4, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={error || undefined}
      className={cn(
        "w-full resize-y rounded-md border border-input bg-background p-3 text-sm placeholder:text-muted-foreground transition-colors focus:border-transparent focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        error && "border-state-error focus:ring-state-error",
        className,
      )}
      {...props}
    />
  );
});
