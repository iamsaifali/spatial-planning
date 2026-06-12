"use client";

import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

/** Bottom sheet on mobile, right-side drawer from sm upward. */
export function Sheet({
  open,
  onClose,
  title,
  children,
  side = "right",
  footer,
  widthClass = "sm:max-w-md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  side?: "right" | "left" | "bottom";
  footer?: ReactNode;
  widthClass?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const placement =
    side === "bottom"
      ? "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-xl"
      : side === "left"
        ? `inset-y-0 left-0 h-full w-full ${widthClass} border-r border-line`
        : `inset-y-0 right-0 h-full w-full ${widthClass} border-l border-line`;

  return (
    <div className="pointer-events-auto fixed inset-0 z-50" role="dialog" aria-modal="true">
      <button
        aria-label="Close panel"
        className="absolute inset-0 bg-ink/35"
        onClick={onClose}
        tabIndex={-1}
      />
      <div className={`absolute z-10 flex flex-col bg-surface shadow-pop ${placement}`}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-sm font-semibold tracking-tight">{title}</div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-ink-soft hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="panel-scroll flex-1 overflow-y-auto">{children}</div>
        {footer && (
          <div className="border-t border-line px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
