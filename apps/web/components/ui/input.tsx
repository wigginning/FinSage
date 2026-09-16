"use client";

/**
 * Input — 统一输入框（替代 21 处散落写法 `h-9 rounded-md border border-input bg-card pl-9 ...`）。
 * 形态：`size` 控制密度，`leadingIcon` / `trailingIcon` 提供图标槽位（用于搜索框前缀图标），
 * `error` 开启错误描边 + aria-invalid。
 */
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const BASE = "w-full rounded-md border border-input bg-background text-sm placeholder:text-muted-foreground transition-colors focus:border-transparent focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

const SIZE = {
  sm: "h-8 px-2.5",
  md: "h-9 px-3",
  lg: "h-10 px-3.5 text-base",
} as const;

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  inputSize?: keyof typeof SIZE;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  error?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, inputSize = "md", leadingIcon, trailingIcon, error, type = "text", ...props },
  ref,
) {
  const hasLeft = Boolean(leadingIcon);
  const hasRight = Boolean(trailingIcon);
  return (
    <div className={cn("relative w-full", className)}>
      {leadingIcon ? (
        <span
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground [&_svg]:h-4 [&_svg]:w-4"
          aria-hidden="true"
        >
          {leadingIcon}
        </span>
      ) : null}
      <input
        ref={ref}
        type={type}
        aria-invalid={error || undefined}
        className={cn(
          BASE,
          SIZE[inputSize],
          hasLeft && "pl-9",
          hasRight && "pr-9",
          error && "border-state-error focus:ring-state-error",
        )}
        {...props}
      />
      {trailingIcon ? (
        <span
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground [&_svg]:h-4 [&_svg]:w-4"
          aria-hidden="true"
        >
          {trailingIcon}
        </span>
      ) : null}
    </div>
  );
});
