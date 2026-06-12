"use client";

import { FileQuestion, Loader2 } from "lucide-react";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { PlannerShell } from "@/components/layout/PlannerShell";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { useGuideStore } from "@/stores/guideStore";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";

export default function SharedDesignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .getDesign(id)
      .then((design) => {
        if (cancelled) return;
        usePlannerStore.getState().loadDesign(design.design_id, design.name, design.room, design.placed_items);
        usePrefsStore.getState().setPreferences(design.preferences);
        useGuideStore.getState().invalidateAll();
        setState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setState(err instanceof ApiError && err.status === 404 ? "missing" : "error");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state === "loading") {
    return (
      <div className="flex h-dvh items-center justify-center gap-2 text-sm text-ink-soft">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading design…
      </div>
    );
  }
  if (state === "missing" || state === "error") {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
        <FileQuestion className="h-10 w-10 text-ink-faint" />
        <h1 className="text-lg font-bold">
          {state === "missing" ? "This design doesn't exist" : "Couldn't load this design"}
        </h1>
        <p className="max-w-xs text-sm text-ink-soft">
          {state === "missing"
            ? "The link may be wrong, or the design was never saved."
            : "Check that the backend is running, then refresh."}
        </p>
        <Link href="/planner">
          <Button>Start a new room</Button>
        </Link>
      </div>
    );
  }
  return <PlannerShell skipDraftRestore />;
}
