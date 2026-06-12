"use client";

/** Orchestrates the place -> validate -> warn -> fix loop shared by
 *  recommendation cards, the quick-add tray and canvas drags. */

import { api, ApiError, NetworkError, debounced } from "@/lib/api";
import { useGuideStore } from "@/stores/guideStore";
import { newInstanceId, usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import type { PlacedItem, Pose, Product } from "@/types/api";

function othersOf(instanceId: string): PlacedItem[] {
  return usePlannerStore.getState().items.filter((i) => i.instance_id !== instanceId);
}

export async function validateItem(instanceId: string): Promise<void> {
  const { room, items } = usePlannerStore.getState();
  const item = items.find((i) => i.instance_id === instanceId);
  const ui = useUiStore.getState();
  if (!item) {
    ui.setWarning(null);
    return;
  }
  ui.setPendingValidation(instanceId);
  try {
    const result = await api.validatePlacement(room, othersOf(instanceId), item);
    const current = useUiStore.getState();
    current.setPendingValidation(null);
    if (result.findings.length > 0) {
      current.setWarning({ instanceId, result });
    } else if (current.warning?.instanceId === instanceId) {
      current.setWarning(null);
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    useUiStore.getState().setPendingValidation(null);
    if (err instanceof NetworkError) {
      useUiStore.getState().toast("error", err.message);
    }
  }
}

export const validateItemDebounced = debounced((instanceId: string) => {
  void validateItem(instanceId);
}, 300);

export async function addProductToRoom(
  product: Product,
  opts: { pose?: Pose; zoneId?: string | null; advance?: boolean } = {},
): Promise<string | null> {
  const planner = usePlannerStore.getState();
  const ui = useUiStore.getState();
  useProductStore.getState().remember([product]);

  let pose = opts.pose ?? null;
  let zoneId = opts.zoneId ?? null;
  if (!pose) {
    try {
      const suggestion = await api.suggestPlacement(
        planner.room,
        planner.items,
        product.id,
        opts.zoneId,
      );
      pose = suggestion.pose;
      zoneId = suggestion.zone_id;
    } catch (err) {
      if (err instanceof ApiError || err instanceof NetworkError) {
        ui.toast("error", err.message);
      }
      return null;
    }
  }

  const instanceId = newInstanceId(product.id);
  planner.addItem({
    instance_id: instanceId,
    product_id: product.id,
    x: pose.x,
    y: pose.y,
    rotation_deg: pose.rotation_deg,
    zone_id: zoneId,
  });
  ui.select(instanceId);
  void validateItem(instanceId);

  if (opts.advance !== false) {
    useGuideStore.getState().advanceAfterPlacement();
  }
  return instanceId;
}

export function applyAutofix(instanceId: string, pose: Pose): void {
  usePlannerStore.getState().moveItem(instanceId, pose);
  useUiStore.getState().setWarning(null);
  useUiStore.getState().setGhost(null);
  void validateItem(instanceId);
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

export async function swapProduct(instanceId: string, next: Product): Promise<void> {
  const planner = usePlannerStore.getState();
  const item = planner.items.find((i) => i.instance_id === instanceId);
  if (!item) return;
  useProductStore.getState().remember([next]);

  // try keeping the current pose; if the new piece can't sit there, re-suggest
  planner.swapItem(instanceId, next.id);
  try {
    const result = await api.validatePlacement(
      planner.room,
      othersOf(instanceId),
      { ...item, product_id: next.id },
    );
    const hasErrors = result.findings.some((f) => f.severity === "error");
    if (hasErrors && result.better_placement) {
      planner.moveItem(instanceId, result.better_placement.pose);
    } else if (hasErrors && result.autofix) {
      planner.moveItem(instanceId, result.autofix.pose);
    }
    void validateItem(instanceId);
  } catch {
    // validation is advisory; the swap itself already happened
  }
  useUiStore.getState().toast("success", `Swapped to ${next.name}`);
}

let customCounter = 0;

/** Place an item the user already owns ("existing items you want to keep"). */
export function addCustomItemToRoom(spec: {
  name: string;
  width_cm: number;
  depth_cm: number;
  height_cm: number;
}): string {
  customCounter += 1;
  const productId = `custom-${Date.now().toString(36)}-${customCounter}`;
  const pseudo: Product = {
    id: productId,
    name: spec.name,
    brand: "Your item",
    category: "custom",
    price: 0,
    mrp: null,
    width_cm: spec.width_cm,
    depth_cm: spec.depth_cm,
    height_cm: spec.height_cm,
    style_tags: [],
    colors: [],
    materials: [],
    in_stock: true,
    delivery_days: 1,
    rating: 0,
    attrs: {},
    image_url: "",
    is_walkable: false,
    shape: "rect",
    description: "",
  };
  useProductStore.getState().remember([pseudo]);

  const planner = usePlannerStore.getState();
  // drop it near the room centre; the user drags it to where it lives
  const xs = planner.room.vertices.map((v) => v[0]);
  const ys = planner.room.vertices.map((v) => v[1]);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;

  const instanceId = newInstanceId(productId);
  planner.addItem({
    instance_id: instanceId,
    product_id: productId,
    x: cx,
    y: cy,
    rotation_deg: 0,
    custom: spec,
  });
  useUiStore.getState().select(instanceId);
  void validateItem(instanceId);
  return instanceId;
}

export function removeItem(instanceId: string): void {
  usePlannerStore.getState().removeItem(instanceId);
  const ui = useUiStore.getState();
  if (ui.selectedId === instanceId) ui.select(null);
  if (ui.warning?.instanceId === instanceId) ui.setWarning(null);
  ui.setGhost(null);
}

/** After room edits: re-check every placed item and badge the troubled ones. */
export async function revalidateAll(): Promise<void> {
  const { room, items } = usePlannerStore.getState();
  const issues: Record<string, "error" | "warning"> = {};
  for (const item of items) {
    try {
      const result = await api.validatePlacement(
        room,
        items.filter((i) => i.instance_id !== item.instance_id),
        item,
      );
      const worst = result.findings.reduce<"error" | "warning" | null>((acc, f) => {
        if (f.severity === "error") return "error";
        if (f.severity === "warning" && acc !== "error") return "warning";
        return acc;
      }, null);
      if (worst) issues[item.instance_id] = worst;
    } catch {
      return; // backend unreachable - badges would be stale guesses
    }
  }
  useUiStore.getState().setItemIssues(issues);
  const count = Object.keys(issues).length;
  if (count > 0) {
    useUiStore.getState().toast("info", `Room changed - ${count} item${count > 1 ? "s" : ""} may need repositioning.`);
  }
}
