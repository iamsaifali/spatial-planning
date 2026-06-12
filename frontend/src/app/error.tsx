"use client";

import { AlertTriangle } from "lucide-react";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-bg p-6 text-center">
      <AlertTriangle className="h-10 w-10 text-warn" />
      <h1 className="text-2xl font-black tracking-tight">Something went wrong</h1>
      <p className="max-w-sm text-sm leading-6 text-ink-soft">
        An unexpected error occurred. Your draft is saved locally - reloading should bring everything back.
      </p>
      <button
        onClick={reset}
        className="rounded-full bg-accent px-6 py-3 text-sm font-semibold text-accent-ink hover:bg-ink-soft"
      >
        Try again
      </button>
    </div>
  );
}
