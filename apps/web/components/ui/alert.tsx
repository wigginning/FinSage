"use client";

/**
 * Alert — 走查发现"加载失败"用裸 `rounded-md bg-state-error-bg ... role="alert"`，无图标无标题。
 * 统一为带图标 + 标题 + 描述 + 可关闭的条状提示，替代 pages 里手写的内联错误条。
 */
import { cva, type VariantProps } from "class-variance-authority";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useState, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const alert = cva(
  "flex items-start gap-3 rounded-md border px-3 py-2.5 text-sm",
  {
    variants: {
      variant: {
        info: "border-state-info/30 bg-state-info-bg text-state-info",
        success: "border-state-success/30 bg-state-success-bg text-state-success",
        warning: "border-state-warning/30 bg-state-warning-bg text-state-warning",
        error: "border-state-error/30 bg-state-error-bg text-state-error",
      },
    },
    defaultVariants: { variant: "info" },
  },
);

const ICON = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
} as const;

// `title` 在本组件是 ReactNode 语义块（标题行），与 DOM 原生 `title: string`（tooltip）
// 冲突，故从 HTMLAttributes 中剔除后重新声明。
export interface AlertProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof alert> {
  title?: ReactNode;
  description?: ReactNode;
  dismissible?: boolean;
}

export function Alert({
  className,
  variant = "info",
  title,
  description,
  dismissible,
  children,
  ...props
}: AlertProps) {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  const Icon = ICON[variant ?? "info"];
  return (
    <div
      role={variant === "error" || variant === "warning" ? "alert" : "status"}
      className={cn(alert({ variant }), className)}
      {...props}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {description ? <p className="mt-0.5 text-sm opacity-90">{description}</p> : null}
        {children}
      </div>
      {dismissible ? (
        <button
          type="button"
          aria-label="关闭"
          onClick={() => setOpen(false)}
          className="rounded p-0.5 opacity-70 transition-opacity hover:opacity-100"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
