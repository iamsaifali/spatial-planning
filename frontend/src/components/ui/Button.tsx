"use client";

import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "amber";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-ink hover:bg-ink-soft active:bg-ink disabled:bg-ink-faint",
  secondary:
    "bg-surface text-ink border border-line-strong hover:border-ink-faint hover:bg-surface-2 disabled:text-ink-faint",
  ghost: "bg-transparent text-ink-soft hover:bg-surface-2 hover:text-ink disabled:text-ink-faint",
  danger: "bg-danger text-white hover:opacity-90 disabled:bg-ink-faint",
  amber: "bg-amber-soft text-amber-deep border border-amber/30 hover:bg-amber-faint disabled:opacity-50",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-sm gap-2",
  icon: "h-10 w-10 shrink-0",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  children?: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-full font-medium transition-[color,background-color,border-color,transform] duration-150 select-none active:scale-[0.97] disabled:cursor-not-allowed disabled:active:scale-100 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
