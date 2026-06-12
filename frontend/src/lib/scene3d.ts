/** Pure geometry for the 3D view: rooms are built from the SAME data as the
 *  2D canvas. Mapping: 2D (x, y_screen) -> 3D (x, z), y up, all metres.
 *  A 2D clockwise rotation maps to -rotation around the 3D Y axis.
 */

import { wallInwardNormal } from "@/lib/geometry";
import type { Room } from "@/types/api";

export const CM = 0.01; // cm -> m

export interface WallBox {
  key: string;
  wall: number;
  center: [number, number, number];
  size: [number, number, number]; // [length, height, thickness]
  rotationY: number;
  kind: "wall" | "lintel" | "sill" | "header";
}

export interface GlassPane {
  key: string;
  wall: number;
  center: [number, number, number];
  size: [number, number, number];
  rotationY: number;
}

export interface WallMeta {
  /** outward-facing unit normal in 3D ground plane (x, z) */
  outward: [number, number];
  /** wall midpoint in metres (x, z) */
  mid: [number, number];
}

interface Span {
  a: number;
  b: number;
  kind: "door" | "window";
  doorHeight?: number;
  sill?: number;
  winHeight?: number;
}

function subtractSpans(length: number, spans: Span[]): [number, number][] {
  const sorted = [...spans].sort((s, t) => s.a - t.a);
  const out: [number, number][] = [];
  let cur = 0;
  for (const span of sorted) {
    const a = Math.max(0, Math.min(span.a, length));
    const b = Math.max(0, Math.min(span.b, length));
    if (a > cur + 0.001) out.push([cur, a]);
    cur = Math.max(cur, b);
  }
  if (cur < length - 0.001) out.push([cur, length]);
  return out.filter(([a, b]) => b - a > 0.02);
}

/** All wall boxes (full segments, lintels above doors, sill+header around windows). */
export function buildWalls(room: Room): { boxes: WallBox[]; glass: GlassPane[]; walls: WallMeta[] } {
  const H = room.wall_height_cm * CM;
  const boxes: WallBox[] = [];
  const glass: GlassPane[] = [];
  const walls: WallMeta[] = [];
  const n = room.vertices.length;

  for (let i = 0; i < n; i++) {
    const [ax, ay] = room.vertices[i];
    const [bx, by] = room.vertices[(i + 1) % n];
    const lenCm = Math.hypot(bx - ax, by - ay);
    const len = lenCm * CM;
    if (len < 0.01) continue;
    const dirX = (bx - ax) / lenCm;
    const dirY = (by - ay) / lenCm;
    const rotationY = -Math.atan2(dirY, dirX);
    const [inX, inY] = wallInwardNormal(room, i);
    walls[i] = {
      outward: [-inX, -inY],
      mid: [((ax + bx) / 2) * CM, ((ay + by) / 2) * CM],
    };

    const at = (tCm: number): [number, number] => [
      (ax + dirX * tCm) * CM,
      (ay + dirY * tCm) * CM,
    ];
    const centerOf = (aCm: number, bCm: number, y: number): [number, number, number] => {
      const [px, pz] = at((aCm + bCm) / 2);
      return [px, y, pz];
    };

    const spans: Span[] = [
      ...room.doors
        .filter((d) => d.wall_index === i)
        .map((d) => ({
          a: d.offset_cm,
          b: d.offset_cm + d.width_cm,
          kind: "door" as const,
          doorHeight: d.height_cm * CM,
        })),
      ...room.windows
        .filter((w) => w.wall_index === i)
        .map((w) => ({
          a: w.offset_cm,
          b: w.offset_cm + w.width_cm,
          kind: "window" as const,
          sill: w.sill_height_cm * CM,
          winHeight: w.height_cm * CM,
        })),
    ];

    // full-height pieces between openings
    for (const [a, b] of subtractSpans(lenCm, spans)) {
      boxes.push({
        key: `w${i}-${a.toFixed(0)}`,
        wall: i,
        center: centerOf(a, b, H / 2),
        size: [(b - a) * CM, H, 0], // thickness filled in by the caller
        rotationY,
        kind: "wall",
      });
    }

    for (const span of spans) {
      const w = (span.b - span.a) * CM;
      if (span.kind === "door") {
        const dh = Math.min(span.doorHeight ?? 2.1, H - 0.02);
        const lintel = H - dh;
        if (lintel > 0.02) {
          boxes.push({
            key: `l${i}-${span.a.toFixed(0)}`,
            wall: i,
            center: centerOf(span.a, span.b, dh + lintel / 2),
            size: [w, lintel, 0],
            rotationY,
            kind: "lintel",
          });
        }
      } else {
        const sill = Math.min(span.sill ?? 0.9, H);
        const wh = Math.min(span.winHeight ?? 1.2, H - sill);
        if (sill > 0.02) {
          boxes.push({
            key: `s${i}-${span.a.toFixed(0)}`,
            wall: i,
            center: centerOf(span.a, span.b, sill / 2),
            size: [w, sill, 0],
            rotationY,
            kind: "sill",
          });
        }
        const header = H - (sill + wh);
        if (header > 0.02) {
          boxes.push({
            key: `h${i}-${span.a.toFixed(0)}`,
            wall: i,
            center: centerOf(span.a, span.b, sill + wh + header / 2),
            size: [w, header, 0],
            rotationY,
            kind: "header",
          });
        }
        glass.push({
          key: `g${i}-${span.a.toFixed(0)}`,
          wall: i,
          center: centerOf(span.a, span.b, sill + wh / 2),
          size: [w, wh, 0.02],
          rotationY,
        });
      }
    }
  }
  return { boxes, glass, walls };
}

export function roomCenter(room: Room): [number, number] {
  const xs = room.vertices.map((v) => v[0]);
  const ys = room.vertices.map((v) => v[1]);
  return [((Math.min(...xs) + Math.max(...xs)) / 2) * CM, ((Math.min(...ys) + Math.max(...ys)) / 2) * CM];
}

export function roomRadius(room: Room): number {
  const xs = room.vertices.map((v) => v[0]);
  const ys = room.vertices.map((v) => v[1]);
  const w = (Math.max(...xs) - Math.min(...xs)) * CM;
  const d = (Math.max(...ys) - Math.min(...ys)) * CM;
  return Math.max(w, d, 2);
}
