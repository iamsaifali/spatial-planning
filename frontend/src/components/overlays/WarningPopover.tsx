"use client";

import { AlertTriangle, Check, Info, Wand2, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { applyAutofix, applyGhost, keepAnyway, showBetterPlacement } from "@/lib/placement";
import { useUiStore } from "@/stores/uiStore";

const SEVERITY_STYLES = {
  error: { icon: AlertTriangle, tone: "text-danger", bg: "bg-danger-soft" },
  warning: { icon: AlertTriangle, tone: "text-warn", bg: "bg-warn-soft" },
  info: { icon: Info, tone: "text-ink-soft", bg: "bg-surface-2" },
};

/** ZORY's soft guidance card: Auto-fix / Show better placement / Keep anyway. */
export function WarningPopover() {
  const warning = useUiStore((s) => s.warning);
  const ghost = useUiStore((s) => s.ghost);
  if (!warning) return null;

  const { findings, autofix, better_placement } = warning.result;
  const top = [...findings].sort(
    (a, b) => ["error", "warning", "info"].indexOf(a.severity) - ["error", "warning", "info"].indexOf(b.severity),
  )[0];
  const extra = findings.length - 1;
  const style = SEVERITY_STYLES[top.severity];
  const Icon = style.icon;

  return (
    <div className="pointer-events-auto w-full max-w-md rounded-lg border border-line bg-surface p-3.5 shadow-pop">
      <div className="flex items-start gap-2.5">
        <span className={`mt-0.5 rounded-full p-1.5 ${style.bg}`}>
          <Icon className={`h-4 w-4 ${style.tone}`} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-5 text-ink">{top.message}</p>
          {extra > 0 && (
            <p className="mt-0.5 text-[11px] text-ink-faint">
              +{extra} more note{extra > 1 ? "s" : ""} on this placement
            </p>
          )}
        </div>
        <button
          onClick={keepAnyway}
          aria-label="Dismiss"
          className="shrink-0 rounded-full p-1 text-ink-faint hover:bg-surface-2 hover:text-ink"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {autofix && (
          <Button size="sm" onClick={() => applyAutofix(warning.instanceId, autofix.pose)}>
            <Wand2 className="h-3.5 w-3.5" />
            Auto-fix
          </Button>
        )}
        {better_placement && !ghost && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => showBetterPlacement(warning.instanceId, better_placement.pose)}
          >
            Show better spot
          </Button>
        )}
        {ghost && (
          <Button size="sm" variant="amber" onClick={() => applyGhost(warning.instanceId)}>
            <Check className="h-3.5 w-3.5" />
            Use suggested spot
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={keepAnyway}>
          Keep anyway
        </Button>
      </div>
    </div>
  );
}
