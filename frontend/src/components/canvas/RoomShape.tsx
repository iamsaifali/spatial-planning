"use client";

import { useState } from "react";
import { Arc, Circle, Group, Line, Rect, Text } from "react-konva";
import {
  polygonArea,
  polygonSelfIntersects,
  wallInwardNormal,
  wallLength,
  wallPointAt,
} from "@/lib/geometry";
import { snapTo } from "@/lib/geometry";
import { GRID_CM } from "@/lib/constants";
import { plannerTemporal, usePlannerStore } from "@/stores/plannerStore";
import { useUiStore } from "@/stores/uiStore";
import type { Door, Point, Room, Window } from "@/types/api";

import { useSceneStore } from "@/stores/sceneStore";

const BG = "#FAFAF8";

/** Wall thickness comes from backend /config (.env); module-level mirror keeps
 *  the many small glyph components free of extra prop drilling. */
let WALL_T = 12;
useSceneStore.subscribe((s) => {
  WALL_T = s.wallThicknessCm;
});

function wallAngleDeg(room: Room, wallIndex: number): number {
  const n = room.vertices.length;
  const [ax, ay] = room.vertices[wallIndex];
  const [bx, by] = room.vertices[(wallIndex + 1) % n];
  return (Math.atan2(by - ay, bx - ax) * 180) / Math.PI;
}

function DimensionLabel({ room, wallIndex, scale }: { room: Room; wallIndex: number; scale: number }) {
  const len = wallLength(room, wallIndex);
  if (len < 50) return null;
  const mid = wallPointAt(room, wallIndex, len / 2);
  const normal = wallInwardNormal(room, wallIndex);
  const off = 24 + 10 / scale;
  let angle = wallAngleDeg(room, wallIndex);
  if (angle > 90 || angle <= -90) angle += 180;
  return (
    <Text
      x={mid[0] - normal[0] * off}
      y={mid[1] - normal[1] * off}
      rotation={angle}
      text={`${(len / 100).toFixed(2)} m`}
      fontSize={12 / scale}
      fontFamily="Inter, sans-serif"
      fill="#78716C"
      align="center"
      width={120}
      offsetX={60}
      offsetY={6 / scale}
      listening={false}
    />
  );
}

function DoorGlyph({
  room,
  door,
  scale,
  interactive,
}: {
  room: Room;
  door: Door;
  scale: number;
  interactive: boolean;
}) {
  const selectOpening = useUiStore((s) => s.selectOpening);
  const selected = useUiStore((s) => s.selectedOpeningId === door.id);
  const updateDoor = usePlannerStore((s) => s.updateDoor);

  const angle = wallAngleDeg(room, door.wall_index);
  const normal = wallInwardNormal(room, door.wall_index);
  const dirAngle = (angle * Math.PI) / 180;
  const dir: Point = [Math.cos(dirAngle), Math.sin(dirAngle)];
  // local +y is the inward side when the perp of dir matches the inward normal
  const s = -dir[1] * normal[0] + dir[0] * normal[1] > 0 ? 1 : -1;
  const start = wallPointAt(room, door.wall_index, door.offset_cm);
  const w = door.width_cm;
  const hingeX = door.hinge === "left" ? 0 : w;
  const leafDir = door.hinge === "left" ? 1 : -1;

  return (
    <Group
      x={start[0]}
      y={start[1]}
      rotation={angle}
      draggable={interactive}
      listening={interactive}
      onClick={(e) => {
        e.cancelBubble = true;
        selectOpening(door.id);
      }}
      onTap={(e) => {
        e.cancelBubble = true;
        selectOpening(door.id);
      }}
      onDragStart={(e) => {
        e.cancelBubble = true;
        plannerTemporal.getState().pause();
        selectOpening(door.id);
      }}
      dragBoundFunc={function (pos) {
        const stage = this.getStage();
        if (!stage) return pos;
        const transform = stage.getAbsoluteTransform().copy().invert();
        const world = transform.point(pos);
        const len = wallLength(room, door.wall_index);
        const [ax, ay] = room.vertices[door.wall_index];
        const t = Math.max(
          0,
          Math.min(len - w, (world.x - ax) * dir[0] + (world.y - ay) * dir[1]),
        );
        const snapped = wallPointAt(room, door.wall_index, snapTo(t, 5));
        return stage.getAbsoluteTransform().point({ x: snapped[0], y: snapped[1] });
      }}
      onDragEnd={(e) => {
        const node = e.target;
        const [ax, ay] = room.vertices[door.wall_index];
        const t = (node.x() - ax) * dir[0] + (node.y() - ay) * dir[1];
        plannerTemporal.getState().resume();
        updateDoor(door.id, { offset_cm: Math.max(0, Math.round(t)) });
      }}
    >
      {/* opening gap erases the wall stroke */}
      <Rect x={0} y={-WALL_T / 2 - 1} width={w} height={WALL_T + 2} fill={BG} />
      {/* swing arc + leaf */}
      {door.swing === "inward" && (
        <Arc
          x={hingeX}
          y={0}
          innerRadius={0}
          outerRadius={w}
          angle={90}
          rotation={s > 0 ? (leafDir > 0 ? 0 : 90) : leafDir > 0 ? -90 : 180}
          fill="#1C1917"
          opacity={0.05}
          stroke="#A8A29E"
          strokeWidth={1 / scale}
          dash={[5 / scale, 4 / scale]}
          listening={false}
        />
      )}
      {door.swing !== "sliding" && door.swing !== "opening_only" && (
        <Line
          points={[hingeX, 0, hingeX, s * (door.swing === "inward" ? w : -w)]}
          stroke="#57534E"
          strokeWidth={2.5}
          lineCap="round"
          listening={false}
        />
      )}
      {door.swing === "sliding" && (
        <Line points={[4, s * 4, w - 4, s * 4]} stroke="#57534E" strokeWidth={2.5} listening={false} />
      )}
      {/* selection / hit area */}
      <Rect
        x={-4}
        y={-WALL_T - 4}
        width={w + 8}
        height={WALL_T * 2 + 8}
        fill="transparent"
        stroke={selected ? "#B45309" : undefined}
        strokeWidth={1.6 / scale}
        dash={[6 / scale, 4 / scale]}
        cornerRadius={4}
      />
    </Group>
  );
}

function WindowGlyph({
  room,
  win,
  scale,
  interactive,
}: {
  room: Room;
  win: Window;
  scale: number;
  interactive: boolean;
}) {
  const selectOpening = useUiStore((s) => s.selectOpening);
  const selected = useUiStore((s) => s.selectedOpeningId === win.id);
  const updateWindow = usePlannerStore((s) => s.updateWindow);

  const angle = wallAngleDeg(room, win.wall_index);
  const dirAngle = (angle * Math.PI) / 180;
  const dir: Point = [Math.cos(dirAngle), Math.sin(dirAngle)];
  const start = wallPointAt(room, win.wall_index, win.offset_cm);
  const w = win.width_cm;

  return (
    <Group
      x={start[0]}
      y={start[1]}
      rotation={angle}
      draggable={interactive}
      listening={interactive}
      onClick={(e) => {
        e.cancelBubble = true;
        selectOpening(win.id);
      }}
      onTap={(e) => {
        e.cancelBubble = true;
        selectOpening(win.id);
      }}
      onDragStart={(e) => {
        e.cancelBubble = true;
        plannerTemporal.getState().pause();
        selectOpening(win.id);
      }}
      dragBoundFunc={function (pos) {
        const stage = this.getStage();
        if (!stage) return pos;
        const transform = stage.getAbsoluteTransform().copy().invert();
        const world = transform.point(pos);
        const len = wallLength(room, win.wall_index);
        const [ax, ay] = room.vertices[win.wall_index];
        const t = Math.max(0, Math.min(len - w, (world.x - ax) * dir[0] + (world.y - ay) * dir[1]));
        const snapped = wallPointAt(room, win.wall_index, snapTo(t, 5));
        return stage.getAbsoluteTransform().point({ x: snapped[0], y: snapped[1] });
      }}
      onDragEnd={(e) => {
        const node = e.target;
        const [ax, ay] = room.vertices[win.wall_index];
        const t = (node.x() - ax) * dir[0] + (node.y() - ay) * dir[1];
        plannerTemporal.getState().resume();
        updateWindow(win.id, { offset_cm: Math.max(0, Math.round(t)) });
      }}
    >
      <Rect x={0} y={-WALL_T / 2 - 1} width={w} height={WALL_T + 2} fill={BG} />
      <Rect x={0} y={-WALL_T / 2} width={w} height={WALL_T} stroke="#57534E" strokeWidth={1.2} fill="#FFFFFF" />
      <Line points={[0, 0, w, 0]} stroke="#57534E" strokeWidth={1} />
      <Rect
        x={-4}
        y={-WALL_T - 4}
        width={w + 8}
        height={WALL_T * 2 + 8}
        fill="transparent"
        stroke={selected ? "#B45309" : undefined}
        strokeWidth={1.6 / scale}
        dash={[6 / scale, 4 / scale]}
        cornerRadius={4}
      />
    </Group>
  );
}

export function RoomShape({ scale, interactive }: { scale: number; interactive: boolean }) {
  const room = usePlannerStore((s) => s.room);
  const commitVertices = usePlannerStore((s) => s.commitVertices);
  const toast = useUiStore((s) => s.toast);
  const [draft, setDraft] = useState<Point[] | null>(null);

  const vertices = draft ?? room.vertices;
  const flat = vertices.flat();
  const draftRoom: Room = draft ? { ...room, vertices: draft } : room;
  const invalid = draft ? polygonSelfIntersects(draft) || polygonArea(draft) < 20_000 : false;

  return (
    <Group>
      {/* floor */}
      <Line points={flat} closed fill="#F3EDE3" listening={false} />
      {/* walls */}
      <Line
        points={flat}
        closed
        stroke={invalid ? "#B91C1C" : "#292524"}
        strokeWidth={WALL_T}
        lineJoin="miter"
        listening={false}
      />

      {!draft &&
        room.doors.map((door) => (
          <DoorGlyph key={door.id} room={room} door={door} scale={scale} interactive={interactive} />
        ))}
      {!draft &&
        room.windows.map((win) => (
          <WindowGlyph key={win.id} room={room} win={win} scale={scale} interactive={interactive} />
        ))}

      {vertices.map((_, i) => (
        <DimensionLabel key={`dim-${i}`} room={draftRoom} wallIndex={i} scale={scale} />
      ))}

      {/* corner handles */}
      {interactive &&
        vertices.map(([x, y], i) => (
          <Circle
            key={`v-${i}`}
            x={x}
            y={y}
            radius={7 / scale}
            fill="#FFFFFF"
            stroke={invalid ? "#B91C1C" : "#1C1917"}
            strokeWidth={1.6 / scale}
            draggable
            onDragStart={(e) => {
              e.cancelBubble = true;
              plannerTemporal.getState().pause();
              setDraft(room.vertices);
            }}
            onDragMove={(e) => {
              e.cancelBubble = true;
              const x2 = snapTo(e.target.x(), GRID_CM);
              const y2 = snapTo(e.target.y(), GRID_CM);
              e.target.position({ x: x2, y: y2 });
              setDraft((prev) => {
                const base = prev ?? room.vertices;
                return base.map((v, j) => (j === i ? ([x2, y2] as Point) : v));
              });
            }}
            onDragEnd={(e) => {
              e.cancelBubble = true;
              const final = (draft ?? room.vertices).map((v, j) =>
                j === i ? ([snapTo(e.target.x(), GRID_CM), snapTo(e.target.y(), GRID_CM)] as Point) : v,
              );
              setDraft(null);
              plannerTemporal.getState().resume();
              if (polygonSelfIntersects(final) || polygonArea(final) < 20_000) {
                toast("error", "That change would make the room invalid, so it was undone.");
                return;
              }
              commitVertices(final);
            }}
          />
        ))}
    </Group>
  );
}
