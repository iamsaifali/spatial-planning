"use client";

/** Registry that lets non-canvas UI (render dialog) snapshot the Konva stage. */

import type Konva from "konva";

let stage: Konva.Stage | null = null;

export function registerStage(s: Konva.Stage | null): void {
  stage = s;
}

/** PNG of room + furniture only (grid/zones/overlays hidden), fit to content. */
export function snapshotCanvas(): string | null {
  if (!stage) return null;
  const hidden: Konva.Layer[] = [];
  for (const layer of stage.getLayers()) {
    if (layer.name() === "decor-layer" && layer.visible()) {
      layer.visible(false);
      hidden.push(layer);
    }
  }
  try {
    const dataUrl = stage.toDataURL({ pixelRatio: 2, mimeType: "image/png" });
    return dataUrl.split(",", 2)[1] ?? null;
  } catch {
    // a cross-origin image (e.g. a product icon) can taint the canvas; never crash the
    // render flow - return null and let the caller render without the reference image
    return null;
  } finally {
    for (const layer of hidden) layer.visible(true);
  }
}
