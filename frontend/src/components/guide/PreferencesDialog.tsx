"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { STYLE_LABELS } from "@/lib/constants";
import { useCurrencyStore } from "@/stores/currencyStore";
import { useGuideStore } from "@/stores/guideStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useUiStore } from "@/stores/uiStore";
import type { Preferences, StyleTag } from "@/types/api";

const COLOR_OPTIONS = ["Beige", "Ivory", "Warm Grey", "Charcoal", "Oak", "Walnut", "Olive", "Terracotta", "Rust", "Mustard"];
const PURPOSES = [
  { key: "family", label: "Family time" },
  { key: "entertaining", label: "Entertaining" },
  { key: "compact_living", label: "Compact living" },
  { key: "work_lounge", label: "Work & lounge" },
] as const;

export function PreferencesDialog() {
  const open = useUiStore((s) => s.prefsOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  const stored = usePrefsStore((s) => s.preferences);
  const setPreferences = usePrefsStore((s) => s.setPreferences);
  const markQuizSeen = usePrefsStore((s) => s.markQuizSeen);
  const currency = useCurrencyStore((s) => s.currency);
  const rates = useCurrencyStore((s) => s.config.rates);
  const rate = rates[currency] ?? 1.0;
  const [draft, setDraft] = useState<Preferences>(stored);

  if (!open) return null;

  const toggleStyle = (style: StyleTag) =>
    setDraft((d) => ({
      ...d,
      styles: d.styles.includes(style) ? d.styles.filter((s) => s !== style) : [...d.styles, style].slice(0, 3),
    }));

  const toggleColor = (color: string) =>
    setDraft((d) => ({
      ...d,
      colors: d.colors.includes(color) ? d.colors.filter((c) => c !== color) : [...d.colors, color].slice(0, 4),
    }));

  const close = () => {
    markQuizSeen();
    setSheet("prefsOpen", false);
  };

  const save = () => {
    setPreferences(draft);
    useGuideStore.getState().invalidateAll();
    void useGuideStore.getState().fetchAnalysis();
    void useGuideStore.getState().fetchStep(undefined, true);
    close();
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Tell ZORY what you like"
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" onClick={close}>
            Skip for now
          </Button>
          <Button onClick={save}>Save preferences</Button>
        </div>
      }
    >
      <div className="space-y-5">
        <p className="text-xs leading-5 text-ink-soft">
          All of this is optional - ZORY works without it, but answers help pick better products.
          Keeping furniture you already own? Add it from the canvas toolbar (&ldquo;Your Item&rdquo;) and
          ZORY will plan around it.
        </p>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">Style (up to 3)</h3>
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(STYLE_LABELS) as StyleTag[]).map((style) => (
              <ToggleChip key={style} active={draft.styles.includes(style)} onClick={() => toggleStyle(style)}>
                {STYLE_LABELS[style]}
              </ToggleChip>
            ))}
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">Budget</h3>
          <div className="flex flex-wrap gap-1.5">
            {(["budget", "mid", "premium"] as const).map((tier) => (
              <ToggleChip
                key={tier}
                active={draft.budget_tier === tier}
                onClick={() => setDraft((d) => ({ ...d, budget_tier: d.budget_tier === tier ? null : tier }))}
              >
                {tier === "budget" ? "Budget-friendly" : tier === "mid" ? "Mid-range" : "Premium"}
              </ToggleChip>
            ))}
          </div>
          <label className="mt-3 block text-xs text-ink-soft">
            Total room budget (optional, {currency})
            <input
              type="number"
              min={100}
              step={100}
              placeholder={currency === "SAR" ? "e.g. 15000" : "e.g. 4000"}
              value={draft.total_budget != null ? Math.round(draft.total_budget * rate) : ""}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  // entered in the display currency; stored in the base currency
                  total_budget: e.target.value ? Math.round(Number(e.target.value) / rate) : null,
                }))
              }
              className="mt-1 block w-44 rounded-md border border-line bg-surface px-3 py-2 text-sm"
            />
          </label>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">Preferred colours (up to 4)</h3>
          <div className="flex flex-wrap gap-1.5">
            {COLOR_OPTIONS.map((color) => (
              <ToggleChip key={color} active={draft.colors.includes(color)} onClick={() => toggleColor(color)}>
                {color}
              </ToggleChip>
            ))}
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-soft">Room is mostly for</h3>
          <div className="flex flex-wrap gap-1.5">
            {PURPOSES.map(({ key, label }) => (
              <ToggleChip
                key={key}
                active={draft.room_purpose === key}
                onClick={() => setDraft((d) => ({ ...d, room_purpose: d.room_purpose === key ? null : key }))}
              >
                {label}
              </ToggleChip>
            ))}
          </div>
        </section>
      </div>
    </Dialog>
  );
}

function ToggleChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
        active ? "border-accent bg-accent text-accent-ink" : "border-line bg-surface text-ink-soft hover:border-ink-faint"
      }`}
    >
      {children}
    </button>
  );
}
