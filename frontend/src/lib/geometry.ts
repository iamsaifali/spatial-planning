/** Lightweight client-side geometry for instant drag feedback.
 *  Advisory only - the backend verdict (placement/validate) always wins.
 *  Mirrors the backend convention: y grows down; at 0 deg width is along +x,
 *  the front faces +y.
 */

import type { Point, Room } from "@/types/api";

export interface Rect {
  cx: number;
  cy: number;
  w: number;
  d: number;
  rot: number; // degrees
}

export function rectCorners({ cx, cy, w, d, rot }: Rect): Point[] {
  const r = (rot * Math.PI) / 180;
  const cos = Math.cos(r);
  const sin = Math.sin(r);
  const hw = w / 2;
  const hd = d / 2;
  const local: Point[] = [
    [-hw, -hd],
    [hw, -hd],
    [hw, hd],
    [-hw, hd],
  ];
  return local.map(([x, y]) => [cx + x * cos - y * sin, cy + x * sin + y * cos]);
}

function projectOnto(corners: Point[], axis: Point): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const [x, y] of corners) {
    const t = x * axis[0] + y * axis[1];
    lo = Math.min(lo, t);
    hi = Math.max(hi, t);
  }
  return [lo, hi];
}

/** Separating-axis overlap test for two rotated rectangles. */
export function rectsOverlap(a: Rect, b: Rect): boolean {
  const ca = rectCorners(a);
  const cb = rectCorners(b);
  const axes: Point[] = [];
  for (const corners of [ca, cb]) {
    for (let i = 0; i < 2; i++) {
      const dx = corners[(i + 1) % 4][0] - corners[i][0];
      const dy = corners[(i + 1) % 4][1] - corners[i][1];
      const len = Math.hypot(dx, dy) || 1;
      axes.push([-dy / len, dx / len]);
    }
  }
  for (const axis of axes) {
    const [aLo, aHi] = projectOnto(ca, axis);
    const [bLo, bHi] = projectOnto(cb, axis);
    if (aHi < bLo + 1 || bHi < aLo + 1) return false;
  }
  return true;
}

export function pointInPolygon([px, py]: Point, polygon: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

export function rectInsidePolygon(rect: Rect, polygon: Point[], slackCm = 2): boolean {
  const grown = growPolygonBBoxTest(rect, polygon, slackCm);
  if (!grown) return false;
  return rectCorners(rect).every((corner) => pointInPolygonWithSlack(corner, polygon, slackCm));
}

function pointInPolygonWithSlack(p: Point, polygon: Point[], slack: number): boolean {
  if (pointInPolygon(p, polygon)) return true;
  return distanceToPolygonEdge(p, polygon) <= slack;
}

function growPolygonBBoxTest(rect: Rect, polygon: Point[], slack: number): boolean {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of polygon) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  return rectCorners(rect).every(
    ([x, y]) =>
      x >= minX - slack && x <= maxX + slack && y >= minY - slack && y <= maxY + slack,
  );
}

export function distanceToPolygonEdge([px, py]: Point, polygon: Point[]): number {
  let best = Infinity;
  for (let i = 0; i < polygon.length; i++) {
    const [ax, ay] = polygon[i];
    const [bx, by] = polygon[(i + 1) % polygon.length];
    const abx = bx - ax;
    const aby = by - ay;
    const t = Math.max(0, Math.min(1, ((px - ax) * abx + (py - ay) * aby) / (abx * abx + aby * aby || 1)));
    best = Math.min(best, Math.hypot(px - (ax + t * abx), py - (ay + t * aby)));
  }
  return best;
}

export function wallLength(room: Room, wallIndex: number): number {
  const n = room.vertices.length;
  const [ax, ay] = room.vertices[wallIndex];
  const [bx, by] = room.vertices[(wallIndex + 1) % n];
  return Math.hypot(bx - ax, by - ay);
}

export function wallPointAt(room: Room, wallIndex: number, t: number): Point {
  const n = room.vertices.length;
  const [ax, ay] = room.vertices[wallIndex];
  const [bx, by] = room.vertices[(wallIndex + 1) % n];
  const len = Math.hypot(bx - ax, by - ay) || 1;
  return [ax + ((bx - ax) / len) * t, ay + ((by - ay) / len) * t];
}

/** Closest wall to a point: returns wall index, offset along it, and distance. */
export function nearestWall(room: Room, p: Point): { wall: number; offset: number; dist: number } {
  let best = { wall: 0, offset: 0, dist: Infinity };
  const n = room.vertices.length;
  for (let i = 0; i < n; i++) {
    const [ax, ay] = room.vertices[i];
    const [bx, by] = room.vertices[(i + 1) % n];
    const abx = bx - ax;
    const aby = by - ay;
    const len2 = abx * abx + aby * aby || 1;
    const t = Math.max(0, Math.min(1, ((p[0] - ax) * abx + (p[1] - ay) * aby) / len2));
    const qx = ax + t * abx;
    const qy = ay + t * aby;
    const dist = Math.hypot(p[0] - qx, p[1] - qy);
    if (dist < best.dist) {
      best = { wall: i, offset: t * Math.sqrt(len2), dist };
    }
  }
  return best;
}

export function polygonSelfIntersects(vertices: Point[]): boolean {
  const n = vertices.length;
  if (n < 4) return false;
  const segs: [Point, Point][] = [];
  for (let i = 0; i < n; i++) {
    segs.push([vertices[i], vertices[(i + 1) % n]]);
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      // skip adjacent segments (shared vertex)
      if (j === i || (j + 1) % n === i || (i + 1) % n === j) continue;
      if (segmentsIntersect(segs[i], segs[j])) return true;
    }
  }
  return false;
}

function segmentsIntersect([a, b]: [Point, Point], [c, d]: [Point, Point]): boolean {
  const o = (p: Point, q: Point, r: Point) =>
    Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
  const o1 = o(a, b, c);
  const o2 = o(a, b, d);
  const o3 = o(c, d, a);
  const o4 = o(c, d, b);
  return o1 !== o2 && o3 !== o4 && o1 !== 0 && o2 !== 0 && o3 !== 0 && o4 !== 0;
}

export function polygonArea(vertices: Point[]): number {
  let area = 0;
  for (let i = 0; i < vertices.length; i++) {
    const [x1, y1] = vertices[i];
    const [x2, y2] = vertices[(i + 1) % vertices.length];
    area += x1 * y2 - x2 * y1;
  }
  return Math.abs(area) / 2;
}

export function roomBBox(room: Room): { minX: number; minY: number; w: number; h: number } {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of room.vertices) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  return { minX, minY, w: maxX - minX, h: maxY - minY };
}

/** Inward normal of a wall, assuming the polygon is simple (frontend mirror of backend logic). */
export function wallInwardNormal(room: Room, wallIndex: number): Point {
  const n = room.vertices.length;
  const [ax, ay] = room.vertices[wallIndex];
  const [bx, by] = room.vertices[(wallIndex + 1) % n];
  const len = Math.hypot(bx - ax, by - ay) || 1;
  const candidate: Point = [-(by - ay) / len, (bx - ax) / len];
  const mid: Point = [(ax + bx) / 2, (ay + by) / 2];
  const probe: Point = [mid[0] + candidate[0] * 5, mid[1] + candidate[1] * 5];
  if (pointInPolygon(probe, room.vertices)) return candidate;
  return [-candidate[0], -candidate[1]];
}

export function snapTo(value: number, step: number): number {
  return Math.round(value / step) * step;
}
