"use client";

import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useUiStore } from "@/stores/uiStore";

const ICONS = {
  info: Info,
  success: CheckCircle2,
  error: AlertTriangle,
};

const TONES = {
  info: "border-line bg-surface text-ink",
  success: "border-success/30 bg-success-soft text-success",
  error: "border-danger/30 bg-danger-soft text-danger",
};

export function Toasts() {
  const toasts = useUiStore((s) => s.toasts);
  const dismiss = useUiStore((s) => s.dismissToast);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-14 z-[70] flex flex-col items-center gap-2 px-4"
    >
      {toasts.map((toast) => {
        const Icon = ICONS[toast.kind];
        return (
          <div
            key={toast.id}
            className={`pointer-events-auto flex w-full max-w-md items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm shadow-pop ${TONES[toast.kind]}`}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p className="flex-1 leading-5">{toast.message}</p>
            <button
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss"
              className="shrink-0 opacity-60 hover:opacity-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
