"use client";

/** "Assist with AI": request a whole-room layout, preview it as ghosts, accept/dismiss.
 *  Plus the client-side item operations (move, auto-fix, remove) the canvas uses.
 *
 *  The assist-only backend has no per-item validate/suggest endpoint, so there are no
 *  live collision warnings — items move freely and `validateItem` is a no-op kept so the
 *  canvas drag handlers still have something to call. */

import { api, ApiError, NetworkError } from "@/lib/api";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import type { AssistLayoutResponse, AssistTemplate, PlacedItem, Pose } from "@/types/api";

/** No live validation on the assist-only backend; clear any stale pending/warning state. */
export function validateItem(instanceId: string): void {
  const ui = useUiStore.getState();
  ui.setPendingValidation(null);
  if (ui.warning?.instanceId === instanceId) ui.setWarning(null);
}

export function validateItemDebounced(instanceId: string): void {
  validateItem(instanceId);
}

export function applyAutofix(instanceId: string, pose: Pose): void {
  usePlannerStore.getState().moveItem(instanceId, pose);
  useUiStore.getState().setWarning(null);
  useUiStore.getState().setGhost(null);
  validateItem(instanceId);
}

export function showBetterPlacement(instanceId: string, pose: Pose): void {
  const item = usePlannerStore.getState().items.find((i) => i.instance_id === instanceId);
  if (!item) return;
  useUiStore.getState().setGhost({
    productId: item.product_id,
    pose,
    label: "Suggested spot",
  });
}

export function applyGhost(instanceId: string): void {
  const ghost = useUiStore.getState().ghost;
  if (!ghost) return;
  applyAutofix(instanceId, ghost.pose);
}

export function keepAnyway(): void {
  useUiStore.getState().setWarning(null);
  useUiStore.getState().setGhost(null);
}

export function removeItem(instanceId: string): void {
  usePlannerStore.getState().removeItem(instanceId);
  const ui = useUiStore.getState();
  if (ui.selectedId === instanceId) ui.select(null);
  if (ui.warning?.instanceId === instanceId) ui.setWarning(null);
  ui.setGhost(null);
}

// --- Assist with AI: request -> preview ghosts -> accept ----------------------------

/** Stage a backend proposal as ghost items (nothing committed until the user accepts). */
export function previewLayout(proposal: AssistLayoutResponse): void {
  // remember products so the ghost furniture can render (dims / image by id)
  useProductStore.getState().remember(proposal.placements.map((p) => p.product));
  const ghosts: PlacedItem[] = proposal.placements.map((p) => ({
    instance_id: p.instance_id,
    product_id: p.product_id,
    x: p.pose.x,
    y: p.pose.y,
    rotation_deg: p.pose.rotation_deg,
    zone_id: p.zone_id,
  }));
  usePlannerStore.getState().setProposedItems(ghosts);
}

/** Ask the backend for layout templates and preview the recommended one. Backend is the
 *  source of truth for geometry; this only renders. Returns the templates (for the picker)
 *  or [] on error/abort. */
export async function requestLayout(): Promise<AssistTemplate[]> {
  const planner = usePlannerStore.getState();
  const ui = useUiStore.getState();
  const { preferences } = usePrefsStore.getState();
  try {
    const { templates } = await api.assistLayout(planner.room, planner.items, preferences, {
      // only living_room / bedroom are planner room types; clamp anything else (e.g. a
      // stale persisted "majlis" pref) to living_room so the backend always has a recipe
      room_type: preferences.room_type === "bedroom" ? "bedroom" : "living_room",
    });
    const rec = templates.find((t) => t.recommended) ?? templates[0];
    if (!rec || rec.layout.placements.length === 0) {
      ui.toast("info", "No fitting layout found - try enlarging the room or easing preferences.");
      return templates;
    }
    previewLayout(rec.layout);
    const n = templates.length;
    ui.toast(
      "success",
      n > 1 ? `${n} layouts - tap one to preview, then accept.` : "Suggested layout - review, then accept.",
    );
    // Surface the recommended template's "didn't fit" notices (already display-ready
    // strings from the backend). Cap the toast spam: show up to 2, summarise the rest.
    const notices = rec.layout.notices ?? [];
    if (notices.length > 0) {
      const shown = notices.slice(0, 2);
      shown.forEach((notice) => ui.toast("info", notice));
      const extra = notices.length - shown.length;
      if (extra > 0) ui.toast("info", `+${extra} more item${extra > 1 ? "s" : ""} couldn't be placed.`);
    }
    return templates;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return [];
    if (err instanceof ApiError || err instanceof NetworkError) ui.toast("error", err.message);
    return [];
  }
}

/** Commit every ghost as a real placed item (re-minted ids). */
export function acceptLayout(): void {
  const planner = usePlannerStore.getState();
  if (planner.proposedItems.length === 0) return;
  planner.acceptProposedItems();
  useUiStore.getState().toast("success", "Layout added - drag to fine-tune.");
}

/** Commit a single ghost (used when the user taps one suggested item on the canvas). */
export function acceptOne(instanceId: string): void {
  usePlannerStore.getState().acceptProposedItem(instanceId);
}

/** Drop all pending ghosts without committing anything. */
export function dismissLayout(): void {
  usePlannerStore.getState().clearProposedItems();
}
