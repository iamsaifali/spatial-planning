"use client";

import { CornerDownLeft, Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useGuideStore } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import type { AssistantResponse } from "@/types/api";

export function AskZory() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<AssistantResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { room, items } = usePlannerStore.getState();
      const prefs = usePrefsStore.getState().preferences;
      const stepKey = useGuideStore.getState().currentStepKey;
      const res = await api.ask(q, room, items, prefs, stepKey);
      setReply(res);
    } catch {
      setError("Couldn't reach ZORY. Check that the backend is running.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-ink">
        <Sparkles className="h-3.5 w-3.5 text-amber-deep" aria-hidden />
        Ask ZORY
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex items-center gap-1.5"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Will a bigger rug work here?"
          maxLength={600}
          className="h-9 min-w-0 flex-1 rounded-full border border-line bg-surface px-3.5 text-xs text-ink placeholder:text-ink-faint"
        />
        <button
          type="submit"
          disabled={busy || !question.trim()}
          aria-label="Ask"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-accent-ink disabled:opacity-40"
        >
          <CornerDownLeft className="h-4 w-4" />
        </button>
      </form>
      {busy && <p className="text-[11px] text-ink-faint">ZORY is thinking…</p>}
      {error && <p className="text-[11px] text-danger">{error}</p>}
      {reply && !busy && (
        <div className="rounded-md bg-surface-2 p-2.5 text-xs leading-5 text-ink-soft">
          <p>{reply.answer}</p>
          {reply.related_tip && <p className="mt-1.5 font-medium text-amber-deep">Tip: {reply.related_tip}</p>}
          {reply.copy_source === "offline" && (
            <p className="mt-1.5 text-[10px] uppercase tracking-wide text-ink-faint">Offline mode</p>
          )}
        </div>
      )}
    </div>
  );
}
