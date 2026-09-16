"use client";

/**
 * Switch — 走查发现设置页用浏览器原生 checkbox + label，视觉与全局不统一。
 * 提供受控 Switch 组件（onCheckedChange），与 Alert 风格的 checkbox 视觉一致。
 */
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const track = cva(
  "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      checked: {
        true: "bg-primary",
        false: "bg-muted",
      },
    },
    defaultVariants: { checked: false },
  },
);

const thumb = cva(
  "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
  {
    variants: {
      checked: {
        true: "translate-x-4",
        false: "translate-x-0.5",
      },
    },
    defaultVariants: { checked: false },
  },
);

export interface SwitchProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange">,
    VariantProps<typeof track> {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  { className, checked = false, onCheckedChange, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange?.(!checked)}
      className={cn(track({ checked }), className)}
      {...props}
    >
      <span className={cn(thumb({ checked }))} />
    </button>
  );
});
