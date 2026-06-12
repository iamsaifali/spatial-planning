import type { ReactNode } from "react";

type Tone = "neutral" | "amber" | "success" | "danger" | "warn" | "ink";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-soft border border-line",
  amber: "bg-amber-soft text-amber-deep border border-amber/25",
  success: "bg-success-soft text-success border border-success/25",
  danger: "bg-danger-soft text-danger border border-danger/25",
  warn: "bg-warn-soft text-warn border border-warn/25",
  ink: "bg-accent text-accent-ink border border-accent",
};

export function Chip({
  tone = "neutral",
  className = "",
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold leading-4 whitespace-nowrap ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
