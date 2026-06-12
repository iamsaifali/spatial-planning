"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
  footer?: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    // pointer-events-auto: dialogs may be portaled-less children of
    // pointer-events-none chrome containers (e.g. the canvas toolbar)
    <div
      className="pointer-events-auto fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <button
        aria-label="Close dialog"
        className="absolute inset-0 bg-ink/40"
        onClick={onClose}
        tabIndex={-1}
      />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`relative z-10 flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-xl bg-surface shadow-pop outline-none sm:m-4 sm:rounded-xl ${
          wide ? "sm:max-w-3xl" : "sm:max-w-lg"
        }`}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-ink-soft hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="panel-scroll flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}
