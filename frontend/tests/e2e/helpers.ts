import { expect, Page } from "@playwright/test";

export const BACKEND = "http://localhost:8000/api/v1";

export type Seats = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
export type Purpose = "Family time" | "Entertaining" | "Compact living" | "Work & lounge";

export interface DraftItem {
  instance_id: string;
  product_id: string;
  x: number;
  y: number;
  rotation_deg: number;
  zone_id?: string | null;
}
export interface Draft {
  room: any;
  items: DraftItem[];
}

/** The 9 guided steps, in order. */
export const STEPS = [
  "Sofa", "TV Unit", "Rug", "Coffee Table", "Side Table",
  "Accent Chair", "Lighting", "Storage", "Decor",
] as const;

/** Dismiss the resume/setup dialogs and land on a blank canvas.
 *  NOTE: the first-run dialog mounts a tick AFTER load, and its full-screen
 *  backdrop intercepts pointer events — so we must WAIT for it and confirm it
 *  is gone before touching the toolbar, or the next click silently blocks. */
async function freshCanvas(page: Page) {
  await page.waitForTimeout(800); // let React mount the first-run dialog

  // "Welcome back" (only if a draft exists) → Start fresh reveals the setup dialog.
  const startFresh = page.getByRole("button", { name: "Start fresh" });
  if (await startFresh.isVisible().catch(() => false)) await startFresh.click();

  // "How do you want to start?" — choose draw-my-own to get a blank canvas we
  // then replace with a precise custom rectangle via Templates.
  const setup = page.getByRole("dialog", { name: "How do you want to start?" });
  await setup.waitFor({ state: "visible", timeout: 12_000 });
  await page.getByRole("button", { name: /Draw my own room/ }).click();
  await setup.waitFor({ state: "hidden", timeout: 10_000 });
}

/** Load a precise W×D (cm) rectangular family living room via the Templates tool. */
export async function setCustomRoom(page: Page, widthCm: number, depthCm: number) {
  await page.goto("/planner");
  await freshCanvas(page);

  await page.getByRole("button", { name: "Templates" }).click();
  await page.getByLabel("Width (cm)").fill(String(widthCm));
  await page.getByLabel("Depth (cm)").fill(String(depthCm));
  await page.getByRole("button", { name: "Create room" }).click();
  // toast confirms; canvas now holds the custom room
  await expect(page.getByRole("button", { name: "Start planning" })).toBeVisible({ timeout: 15_000 });
}

/** Open prefs (quiz), set family + seats (+ optional styles), save → starts planning. */
export async function planFamily(page: Page, seats: Seats, styles: string[] = ["Modern"]) {
  await page.getByRole("button", { name: "Start planning" }).click();

  // The quiz auto-opens on first planning in a clean context.
  const dialog = page.getByRole("dialog", { name: "Tell ZORY what you like" });
  await expect(dialog).toBeVisible({ timeout: 15_000 });

  for (const s of styles) await dialog.getByRole("button", { name: s, exact: true }).click();
  await dialog.getByRole("button", { name: "Family time" }).click();
  const seatLabel = seats === 8 ? "8+" : String(seats);
  await dialog.getByRole("button", { name: seatLabel, exact: true }).click();
  await dialog.getByRole("button", { name: "Save preferences" }).click();

  // First step (Sofa) recommendations confirm the plan→recommend pipeline ran.
  await expect(
    page.getByText(/options that fit your space|No fitting|doesn't fit/i).first(),
  ).toBeVisible({ timeout: 90_000 });
}

/** Walk each step the plan actually produced, adding the best-match product where
 *  one fits. The plan may contain FEWER than 9 categories (tight rooms drop
 *  side_table/storage/etc.), so we advance by index and stop when no further step
 *  button exists rather than assuming all 9. */
export async function placeAllSteps(page: Page) {
  for (let i = 0; i < STEPS.length; i++) {
    // Step buttons render as "1 Sofa" (guide panel, number+label) or "Step 1: Sofa"
    // (collapsed rail aria-label); once placed the number becomes a check icon, so
    // we match the leading index and click before this step is done.
    const stepBtn = page
      .getByRole("button", { name: new RegExp(`^(Step )?${i + 1}[ :]`) })
      .first();
    try {
      await stepBtn.waitFor({ state: "visible", timeout: 6_000 });
    } catch {
      break; // this room's plan has fewer than i+1 steps — done
    }
    await stepBtn.scrollIntoViewIfNeeded();
    await stepBtn.click();
    // Recommendations load via a per-step LLM call (~5–10s). Settle so the previous
    // step's list clears, then wait for THIS step's recs (or a no-fit notice).
    await page.waitForTimeout(2500);
    const addBtn = page.getByRole("button", { name: "Add to room" }).first();
    await addBtn.waitFor({ state: "visible", timeout: 60_000 }).catch(() => {});
    if (await addBtn.isVisible().catch(() => false)) {
      await addBtn.click();
      await page.waitForTimeout(1500); // let the placement settle into the draft
    }
  }
}

/** Read the persisted room + placed items straight from the planner store. */
export async function extractDraft(page: Page): Promise<Draft> {
  return page.evaluate(() => {
    const d = JSON.parse(localStorage.getItem("zory-draft-v1") || "{}");
    return { room: d.room, items: d.items || [] };
  });
}

export interface Finding {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  item_instance_id: string;
  other_instance_id?: string | null;
}

/** Re-validate every placed item against the backend's spatial rules. */
export async function validateAll(draft: Draft): Promise<Finding[]> {
  const all: Finding[] = [];
  for (const item of draft.items) {
    const res = await fetch(`${BACKEND}/placement/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room: draft.room, placed_items: draft.items, item }),
    });
    if (!res.ok) throw new Error(`validate ${item.product_id} -> HTTP ${res.status}`);
    const body = await res.json();
    all.push(...(body.findings || []));
  }
  return all;
}

export const errorsOnly = (f: Finding[]) => f.filter((x) => x.severity === "error");
