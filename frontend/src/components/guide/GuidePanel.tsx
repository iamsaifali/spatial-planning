"use client";

import { CircleAlert, ClipboardList, HelpCircle, Lightbulb, RotateCcw, SkipForward, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { CATEGORY_LABELS, REASON_PHRASES } from "@/lib/constants";
import { STEP_ORDER, useGuideStore } from "@/stores/guideStore";
import { useUiStore } from "@/stores/uiStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { STYLE_LABELS } from "@/lib/constants";
import { AskZory } from "./AskZory";
import { StepList } from "./StepList";

export function GuidePanelContent({ showSteps = true }: { showSteps?: boolean }) {
  const currentStepKey = useGuideStore((s) => s.currentStepKey);
  const stepCache = useGuideStore((s) => s.stepCache);
  const stepLoading = useGuideStore((s) => s.stepLoading);
  const stepError = useGuideStore((s) => s.stepError);
  const skipStep = useGuideStore((s) => s.skipStep);
  const fetchStep = useGuideStore((s) => s.fetchStep);
  const setSheet = useUiStore((s) => s.setSheet);
  const preferences = usePrefsStore((s) => s.preferences);

  const step = stepCache[currentStepKey]?.data;
  const stepNumber = STEP_ORDER.indexOf(currentStepKey) + 1;
  const whyHere = (step?.guidance.reason_codes ?? [])
    .map((code) => REASON_PHRASES[code])
    .filter(Boolean)
    .slice(0, 3);
  const prefChips = [
    ...preferences.styles.map((s) => STYLE_LABELS[s] ?? s),
    preferences.budget_tier ? `${preferences.budget_tier} budget` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="flex h-full flex-col">
      <div className="panel-scroll flex-1 space-y-5 overflow-y-auto p-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Room guide · Step {stepNumber} of {STEP_ORDER.length}
          </p>
          <h2 className="mt-1 text-base font-bold tracking-tight">{CATEGORY_LABELS[currentStepKey]}</h2>
        </div>

        {stepLoading && !step && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}

        {stepError && !step && (
          <div className="space-y-2 rounded-md border border-danger/30 bg-danger-soft p-3">
            <p className="flex items-start gap-2 text-xs leading-5 text-danger">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /> {stepError}
            </p>
            <Button size="sm" variant="secondary" onClick={() => void fetchStep(undefined, true)}>
              <RotateCcw className="h-3.5 w-3.5" /> Retry
            </Button>
          </div>
        )}

        {step && (
          <>
            <p className="text-[13px] leading-6 text-ink-soft">{step.guidance.message}</p>
            {whyHere.length > 0 && (
              <div className="rounded-md border border-amber/25 bg-amber-faint p-3">
                <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-amber-deep">
                  <HelpCircle className="h-3.5 w-3.5" aria-hidden /> Why here?
                </p>
                <ul className="mt-1.5 space-y-1 text-xs leading-5 text-amber-deep">
                  {whyHere.map((phrase) => (
                    <li key={phrase} className="capitalize">• {phrase}</li>
                  ))}
                </ul>
              </div>
            )}
            {step.guidance.tip && (
              <div className="flex items-start gap-2 rounded-md border border-line bg-surface-2/70 p-3">
                <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-deep" aria-hidden />
                <p className="text-xs leading-5 text-ink-soft">{step.guidance.tip}</p>
              </div>
            )}
            <Button variant="ghost" size="sm" onClick={() => skipStep(currentStepKey as never)}>
              <SkipForward className="h-3.5 w-3.5" />
              Skip this step
            </Button>
          </>
        )}

        {prefChips.length > 0 && (
          <button
            onClick={() => setSheet("prefsOpen", true)}
            className="flex flex-wrap items-center gap-1.5 text-left"
            aria-label="Edit preferences"
          >
            {prefChips.map((chip) => (
              <span key={chip} className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-semibold capitalize text-ink-soft">
                {chip}
              </span>
            ))}
            <span className="text-[10px] font-medium text-amber-deep underline underline-offset-2">edit</span>
          </button>
        )}

        {showSteps && (
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">Steps</p>
            <StepList />
          </div>
        )}

        <AskZory />
      </div>

      <div className="space-y-2 border-t border-line p-3">
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => setSheet("prefsOpen", true)}
          size="md"
        >
          <SlidersHorizontal className="h-4 w-4" />
          Preferences
        </Button>
        <Button className="w-full" size="md" onClick={() => setSheet("summaryOpen", true)}>
          <ClipboardList className="h-4 w-4" />
          Room summary
        </Button>
      </div>
    </div>
  );
}

/** Desktop left column. */
export function GuidePanel() {
  return (
    <aside className="hidden h-full min-h-0 flex-col border-r border-line bg-surface xl:flex" aria-label="Room guide">
      <GuidePanelContent />
    </aside>
  );
}

/** Narrow icon rail for lg screens. */
export function StepRail() {
  const setSheet = useUiStore((s) => s.setSheet);
  return (
    <aside
      className="hidden h-full flex-col items-center gap-4 border-r border-line bg-surface py-4 lg:flex xl:hidden"
      aria-label="Steps"
    >
      <StepList compact />
      <button
        onClick={() => setSheet("leftPanelOpen", true)}
        className="mt-auto rounded-full border border-line p-2 text-ink-soft hover:bg-surface-2"
        aria-label="Open guide panel"
        title="Open guide"
      >
        <ClipboardList className="h-4 w-4" />
      </button>
    </aside>
  );
}
