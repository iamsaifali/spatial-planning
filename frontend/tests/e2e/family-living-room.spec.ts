import { test, expect } from "@playwright/test";
import {
  setCustomRoom, planFamily, placeAllSteps, extractDraft, validateAll,
  errorsOnly, Seats,
} from "./helpers";

/**
 * Family-living-room placement matrix.
 *
 * Each case: build a precise W×D room → set Family + N seats → run the guided
 * plan → place the best-match product at every step → extract the real placed
 * geometry → re-validate against the backend's spatial rules.
 *
 * HARD invariant (must always hold): no ERROR-severity findings
 *   (out-of-bounds, item overlap, blocked door swing).
 * SOFT signals (logged, not failed): walkway/clearance/TV/window warnings —
 *   these are design-quality judgements the interior-designer agent reviews.
 */

interface Case { w: number; d: number; seats: Seats; label: string }

const MATRIX: Case[] = [
  { w: 250, d: 250, seats: 2, label: "tiny 2.5×2.5 (can a sofa even fit?)" },
  { w: 300, d: 300, seats: 3, label: "small 3.0×3.0" },
  { w: 480, d: 360, seats: 4, label: "sample 4.8×3.6" },
  { w: 500, d: 400, seats: 5, label: "medium 5.0×4.0" },
  { w: 700, d: 300, seats: 4, label: "long-narrow 7.0×3.0" },
  { w: 600, d: 500, seats: 6, label: "large 6.0×5.0" },
  { w: 800, d: 700, seats: 8, label: "very large 8.0×7.0, 8 seats" },
];

for (const c of MATRIX) {
  test(`family ${c.label} — no error-level placement issues`, async ({ page }) => {
    await setCustomRoom(page, c.w, c.d);
    await planFamily(page, c.seats);
    await placeAllSteps(page);

    const draft = await extractDraft(page);
    expect(draft.items.length, "at least the sofa should be placed").toBeGreaterThan(0);

    const findings = await validateAll(draft);
    const errors = errorsOnly(findings);

    const summary = {
      placed: draft.items.length,
      categories: draft.items.map((i) => i.product_id.replace(/-\d+.*/, "")),
      errors: errors.map((e) => `${e.code}: ${e.message}`),
      warnings: findings.filter((f) => f.severity === "warning").map((f) => f.code),
    };
    console.log(`\n[${c.label}]`, JSON.stringify(summary, null, 2));

    expect(errors, `error-level findings in ${c.label}`).toHaveLength(0);
  });
}
