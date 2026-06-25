"use client";

import { temporal } from "zundo";
import { create } from "zustand";
import { sampleRoom } from "@/lib/constants";
import type { Door, PlacedItem, Point, Pose, Room, Window } from "@/types/api";

let instanceCounter = 0;
export function newInstanceId(productId: string): string {
  instanceCounter += 1;
  return `${productId}-${Date.now().toString(36)}-${instanceCounter}`;
}

/** After vertex moves, openings can overflow their (shorter) wall: clamp or drop. */
function sanitizeOpenings(room: Room): Room {
  const n = room.vertices.length;
  const lengthOf = (i: number) => {
    const [ax, ay] = room.vertices[i];
    const [bx, by] = room.vertices[(i + 1) % n];
    return Math.hypot(bx - ax, by - ay);
  };
  const fit = <T extends { wall_index: number; offset_cm: number; width_cm: number }>(ops: T[]): T[] =>
    ops
      .filter((op) => op.wall_index < n && op.width_cm <= lengthOf(op.wall_index))
      .map((op) => {
        const len = lengthOf(op.wall_index);
        return op.offset_cm + op.width_cm > len
          ? { ...op, offset_cm: Math.max(0, len - op.width_cm) }
          : op;
      });
  return { ...room, doors: fit(room.doors), windows: fit(room.windows) };
}

interface PlannerState {
  room: Room;
  items: PlacedItem[];
  // "Assist with AI" suggestions awaiting the user's accept/dismiss. Kept OUT of
  // the temporal `partialize` below so undo/redo never commits or resurrects ghosts.
  proposedItems: PlacedItem[];
  roomVersion: number; // bumps on every geometry edit (invalidates caches)
  designId: string | null;
  designName: string;
  dirtySinceSave: boolean;

  setRoom: (room: Room) => void;
  replaceVertices: (vertices: Point[]) => void;
  commitVertices: (vertices: Point[]) => void;
  moveVertex: (index: number, p: Point) => void;
  moveWall: (index: number, dx: number, dy: number) => void;
  addDoor: (door: Door) => void;
  addWindow: (window: Window) => void;
  updateDoor: (id: string, patch: Partial<Door>) => void;
  updateWindow: (id: string, patch: Partial<Window>) => void;
  removeOpening: (id: string) => void;

  addItem: (item: PlacedItem) => void;
  moveItem: (instanceId: string, pose: Partial<Pose>) => void;
  removeItem: (instanceId: string) => void;
  swapItem: (instanceId: string, newProductId: string, pose?: Pose) => void;
  clearItems: () => void;

  // proposed/ghost layout (Assist with AI)
  setProposedItems: (items: PlacedItem[]) => void;
  clearProposedItems: () => void;
  acceptProposedItems: () => void;
  acceptProposedItem: (instanceId: string) => void;
  dismissProposedItem: (instanceId: string) => void;

  loadDesign: (designId: string | null, name: string, room: Room, items: PlacedItem[]) => void;
  markSaved: (designId: string) => void;
}

export const usePlannerStore = create<PlannerState>()(
  temporal(
    (set) => ({
      room: sampleRoom(),
      items: [],
      proposedItems: [],
      roomVersion: 0,
      designId: null,
      designName: "My Living Room",
      dirtySinceSave: false,

      setRoom: (room) =>
        set((s) => ({ room, roomVersion: s.roomVersion + 1, dirtySinceSave: true })),

      replaceVertices: (vertices) =>
        set((s) => ({
          // openings reference wall indices; a topology change invalidates them
          room: { ...s.room, vertices, doors: [], windows: [] },
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      commitVertices: (vertices) =>
        set((s) => ({
          room: sanitizeOpenings({ ...s.room, vertices }),
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      moveVertex: (index, p) =>
        set((s) => {
          const vertices = s.room.vertices.map((v, i) => (i === index ? p : v));
          return {
            room: { ...s.room, vertices },
            roomVersion: s.roomVersion + 1,
            dirtySinceSave: true,
          };
        }),

      moveWall: (index, dx, dy) =>
        set((s) => {
          const n = s.room.vertices.length;
          const next = (index + 1) % n;
          const vertices = s.room.vertices.map((v, i) =>
            i === index || i === next ? ([v[0] + dx, v[1] + dy] as Point) : v,
          );
          return {
            room: { ...s.room, vertices },
            roomVersion: s.roomVersion + 1,
            dirtySinceSave: true,
          };
        }),

      addDoor: (door) =>
        set((s) => ({
          room: { ...s.room, doors: [...s.room.doors, door] },
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      addWindow: (window) =>
        set((s) => ({
          room: { ...s.room, windows: [...s.room.windows, window] },
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      updateDoor: (id, patch) =>
        set((s) => ({
          room: {
            ...s.room,
            doors: s.room.doors.map((d) => (d.id === id ? { ...d, ...patch } : d)),
          },
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      updateWindow: (id, patch) =>
        set((s) => ({
          room: {
            ...s.room,
            windows: s.room.windows.map((w) => (w.id === id ? { ...w, ...patch } : w)),
          },
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      removeOpening: (id) =>
        set((s) => ({
          room: {
            ...s.room,
            doors: s.room.doors.filter((d) => d.id !== id),
            windows: s.room.windows.filter((w) => w.id !== id),
          },
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: true,
        })),

      addItem: (item) => set((s) => ({ items: [...s.items, item], dirtySinceSave: true })),

      moveItem: (instanceId, pose) =>
        set((s) => ({
          items: s.items.map((it) =>
            it.instance_id === instanceId ? { ...it, ...pose } : it,
          ),
          dirtySinceSave: true,
        })),

      removeItem: (instanceId) =>
        set((s) => ({
          items: s.items.filter((it) => it.instance_id !== instanceId),
          dirtySinceSave: true,
        })),

      swapItem: (instanceId, newProductId, pose) =>
        set((s) => ({
          items: s.items.map((it) =>
            it.instance_id === instanceId
              ? { ...it, product_id: newProductId, ...(pose ?? {}) }
              : it,
          ),
          dirtySinceSave: true,
        })),

      clearItems: () => set({ items: [], dirtySinceSave: true }),

      // --- Assist with AI: ghost layout staging ---------------------------------
      // Ghosts are never persisted nor tracked by undo/redo. Accepting re-mints a
      // fresh instance_id so a committed item can never collide with an existing one
      // and the proposed id can be re-proposed later without conflict.
      setProposedItems: (proposedItems) => set({ proposedItems }),

      clearProposedItems: () => set({ proposedItems: [] }),

      acceptProposedItems: () =>
        set((s) => ({
          items: [
            ...s.items,
            ...s.proposedItems.map((g) => ({ ...g, instance_id: newInstanceId(g.product_id) })),
          ],
          proposedItems: [],
          dirtySinceSave: true,
        })),

      acceptProposedItem: (instanceId) =>
        set((s) => {
          const ghost = s.proposedItems.find((i) => i.instance_id === instanceId);
          if (!ghost) return {};
          return {
            items: [...s.items, { ...ghost, instance_id: newInstanceId(ghost.product_id) }],
            proposedItems: s.proposedItems.filter((i) => i.instance_id !== instanceId),
            dirtySinceSave: true,
          };
        }),

      dismissProposedItem: (instanceId) =>
        set((s) => ({
          proposedItems: s.proposedItems.filter((i) => i.instance_id !== instanceId),
        })),

      loadDesign: (designId, name, room, items) =>
        set((s) => ({
          designId,
          designName: name,
          room,
          items,
          proposedItems: [],
          roomVersion: s.roomVersion + 1,
          dirtySinceSave: false,
        })),

      markSaved: (designId) => set({ designId, dirtySinceSave: false }),
    }),
    {
      partialize: (state) => ({ room: state.room, items: state.items }),
      limit: 60,
      equality: (a, b) => JSON.stringify(a) === JSON.stringify(b),
    },
  ),
);

export const plannerTemporal = usePlannerStore.temporal;

// Invariant: a room-geometry edit invalidates any pending Assist proposal.
// roomVersion bumps on every geometry change (see PlannerState). Ghost placements were
// validated by the backend against the room as it was at request time, so they must NOT
// survive a room edit - otherwise the user could Accept ghosts that now sit outside the
// room or block a newly added door. Keying off roomVersion catches every geometry
// mutator (incl. undo/redo and any future one) in one place. proposedItems is outside
// the temporal partialize, so clearing it never touches undo/redo history.
usePlannerStore.subscribe((state, prev) => {
  if (state.roomVersion !== prev.roomVersion && state.proposedItems.length > 0) {
    usePlannerStore.setState({ proposedItems: [] });
  }
});

export function undo() {
  plannerTemporal.getState().undo();
  usePlannerStore.setState((s) => ({ roomVersion: s.roomVersion + 1, dirtySinceSave: true }));
}

export function redo() {
  plannerTemporal.getState().redo();
  usePlannerStore.setState((s) => ({ roomVersion: s.roomVersion + 1, dirtySinceSave: true }));
}
