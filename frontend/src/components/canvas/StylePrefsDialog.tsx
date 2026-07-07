"use client";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { COLOR_FAMILIES, FAMILY_SWATCH, STYLES, styleLabel } from "@/lib/styleMetadata";
import { usePrefsStore } from "@/stores/prefsStore";

/** "Pick your style" step shown when the user hits "Assist with AI". Captures a single style and any
 *  number of colour families, which are REQUIRED before generating. Fully store-controlled (each pick
 *  is written straight to Preferences) so the selection survives re-renders; onConfirm then runs the
 *  assist, which reads style/color_families back out of the store. */
export function StylePrefsDialog({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const style = usePrefsStore((s) => s.preferences.style ?? null);
  const families = usePrefsStore((s) => s.preferences.color_families ?? []);
  const setPreferences = usePrefsStore((s) => s.setPreferences);

  const patch = (p: { style?: string | null; color_families?: string[] }) =>
    setPreferences({ ...usePrefsStore.getState().preferences, ...p });

  const pickStyle = (s: string) => patch({ style: style === s ? null : s });
  const toggleFamily = (f: string) =>
    patch({ color_families: families.includes(f) ? families.filter((x) => x !== f) : [...families, f] });

  const canGenerate = style !== null && families.length > 0;
  const generate = () => {
    if (canGenerate) onConfirm();
  };

  return (
    <Dialog open={open} onClose={onClose} title="Pick your style">
      <div className="space-y-4">
        <p className="text-xs leading-5 text-ink-soft">
          Choose a look and the colours you like — we&apos;ll build layouts with matching products.
        </p>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Style</p>
          <div className="flex flex-wrap gap-1.5">
            {STYLES.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => pickStyle(s)}
                aria-pressed={style === s}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  style === s
                    ? "border-ink bg-ink text-surface"
                    : "border-line bg-surface text-ink hover:border-ink-faint"
                }`}
              >
                {styleLabel(s)}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
            Colours <span className="font-normal normal-case text-ink-faint">(pick any)</span>
          </p>
          <div className="flex flex-wrap gap-1.5">
            {COLOR_FAMILIES.map((f) => {
              const on = families.includes(f);
              return (
                <button
                  key={f}
                  type="button"
                  onClick={() => toggleFamily(f)}
                  aria-pressed={on}
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    on ? "border-ink bg-surface-2 text-ink" : "border-line bg-surface text-ink hover:border-ink-faint"
                  }`}
                >
                  <span
                    className="h-3.5 w-3.5 rounded-full border border-black/10"
                    style={{ backgroundColor: FAMILY_SWATCH[f] }}
                    aria-hidden
                  />
                  {f}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 pt-1">
          <p className="text-xs text-ink-faint">
            {canGenerate ? " " : "Pick a style and at least one colour to continue."}
          </p>
          <Button variant="primary" size="sm" disabled={!canGenerate} onClick={generate}>
            Generate layouts
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
