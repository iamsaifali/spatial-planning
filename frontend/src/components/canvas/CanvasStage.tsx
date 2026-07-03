"use client";

import type Konva from "konva";
import type { KonvaEventObject } from "konva/lib/Node";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Circle, Group, Label, Layer, Line, Stage, Tag, Text } from "react-konva";
import { registerStage } from "@/lib/canvasExport";
import { GRID_CM, MAX_ZOOM, MIN_ZOOM } from "@/lib/constants";
import {
  nearestWall,
  polygonArea,
  polygonSelfIntersects,
  roomBBox,
  snapTo,
  wallLength,
} from "@/lib/geometry";
import { acceptOne, removeItem, validateItemDebounced } from "@/lib/placement";
import { redo, undo, usePlannerStore } from "@/stores/plannerStore";
import { useGuideStore } from "@/stores/guideStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import type { Point } from "@/types/api";
import { AssistPanel } from "./AssistPanel";
import { AnalysisOverlay, GhostNode, ProposedItemNode, WarningGeometry } from "./Overlays";
import { PlacedItemNode } from "./PlacedItemNode";
import { RoomShape } from "./RoomShape";

const clampScale = (v: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v));

function orthoSnap(p: Point, last: Point | null): Point {
  let [x, y] = [snapTo(p[0], GRID_CM), snapTo(p[1], GRID_CM)];
  if (last) {
    const dx = Math.abs(x - last[0]);
    const dy = Math.abs(y - last[1]);
    if (dy <= dx * 0.13) y = last[1];
    else if (dx <= dy * 0.13) x = last[0];
  }
  return [x, y];
}

export default function CanvasStage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [scale, setScaleRaw] = useState(1);
  // stable identity so fitToRoom/zoomAt deps stay minimal
  const setScale = useRef((next: number) => {
    setScaleRaw(next);
    useUiStore.getState().setZoomPct(Math.round(next * 100));
  }).current;

  const tool = useUiStore((s) => s.tool);
  const setTool = useUiStore((s) => s.setTool);
  const selectedId = useUiStore((s) => s.selectedId);
  const select = useUiStore((s) => s.select);
  const selectOpening = useUiStore((s) => s.selectOpening);
  const fitCounter = useUiStore((s) => s.fitCounter);
  const zoomNudge = useUiStore((s) => s.zoomNudge);
  const ghost = useUiStore((s) => s.ghost);
  const warning = useUiStore((s) => s.warning);
  const doorWidth = useUiStore((s) => s.doorWidth);
  const windowWidth = useUiStore((s) => s.windowWidth);
  const toast = useUiStore((s) => s.toast);

  const room = usePlannerStore((s) => s.room);
  const items = usePlannerStore((s) => s.items);
  const proposedItems = usePlannerStore((s) => s.proposedItems);
  const replaceVertices = usePlannerStore((s) => s.replaceVertices);
  const addDoor = usePlannerStore((s) => s.addDoor);
  const addWindow = usePlannerStore((s) => s.addWindow);

  const productsById = useProductStore((s) => s.byId);
  const overlaysVisible = useGuideStore((s) => s.overlaysVisible);
  const analysis = useGuideStore((s) => s.analysis);

  // drawing state
  const [draftPoints, setDraftPoints] = useState<Point[]>([]);
  const [cursor, setCursor] = useState<Point | null>(null);
  const [openingGhost, setOpeningGhost] = useState<{
    wall: number;
    offset: number;
    valid: boolean;
  } | null>(null);
  const [measure, setMeasure] = useState<{ a: Point; b: Point | null; frozen: boolean } | null>(null);

  const pinch = useRef<{ dist: number; center: { x: number; y: number } } | null>(null);

  // --- sizing & view transforms ---------------------------------------------

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
    });
    observer.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => observer.disconnect();
  }, []);

  const fitToRoom = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const bbox = roomBBox(usePlannerStore.getState().room);
    const pad = 90;
    const next = clampScale(
      Math.min(
        size.w / (bbox.w + pad * 2),
        size.h / (bbox.h + pad * 2),
      ),
    );
    stage.scale({ x: next, y: next });
    stage.position({
      x: size.w / 2 - (bbox.minX + bbox.w / 2) * next,
      y: size.h / 2 - (bbox.minY + bbox.h / 2) * next,
    });
    setScale(next);
  }, [size.w, size.h, setScale]);

  useEffect(() => {
    fitToRoom();
    // refit when the viewport or an explicit request changes
  }, [fitToRoom, fitCounter]);

  useEffect(() => {
    registerStage(stageRef.current);
    return () => registerStage(null);
  }, []);

  const zoomAt = useCallback((anchor: { x: number; y: number }, factor: number) => {
    const stage = stageRef.current;
    if (!stage) return;
    const old = stage.scaleX();
    const next = clampScale(old * factor);
    const world = { x: (anchor.x - stage.x()) / old, y: (anchor.y - stage.y()) / old };
    stage.scale({ x: next, y: next });
    stage.position({ x: anchor.x - world.x * next, y: anchor.y - world.y * next });
    setScale(next);
  }, [setScale]);

  const prevNudge = useRef(zoomNudge);
  useEffect(() => {
    const delta = zoomNudge - prevNudge.current;
    prevNudge.current = zoomNudge;
    if (delta !== 0) zoomAt({ x: size.w / 2, y: size.h / 2 }, delta > 0 ? 1.25 : 0.8);
  }, [zoomNudge, zoomAt, size.w, size.h]);

  const onWheel = (e: KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const pointer = stageRef.current?.getPointerPosition();
    if (!pointer) return;
    zoomAt(pointer, Math.pow(1.0016, -e.evt.deltaY));
  };

  // --- pinch zoom -------------------------------------------------------------

  const onTouchMove = (e: KonvaEventObject<TouchEvent>) => {
    const touches = e.evt.touches;
    if (touches.length !== 2) return;
    e.evt.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;
    stage.draggable(false);
    const rect = containerRef.current?.getBoundingClientRect();
    const p1 = { x: touches[0].clientX - (rect?.left ?? 0), y: touches[0].clientY - (rect?.top ?? 0) };
    const p2 = { x: touches[1].clientX - (rect?.left ?? 0), y: touches[1].clientY - (rect?.top ?? 0) };
    const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
    const center = { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 };
    if (pinch.current) {
      zoomAt(center, dist / pinch.current.dist);
      stage.position({
        x: stage.x() + center.x - pinch.current.center.x,
        y: stage.y() + center.y - pinch.current.center.y,
      });
    }
    pinch.current = { dist, center };
  };

  const onTouchEnd = () => {
    pinch.current = null;
    stageRef.current?.draggable(tool === "select");
  };

  // --- pointer helpers ----------------------------------------------------------

  const worldPointer = (): Point | null => {
    const stage = stageRef.current;
    const pos = stage?.getRelativePointerPosition();
    return pos ? [pos.x, pos.y] : null;
  };

  const closeRadius = 12 / scale;

  const finishPolygon = useCallback(
    (points: Point[]) => {
      if (points.length < 3) return;
      if (polygonSelfIntersects(points)) {
        toast("error", "Walls can't cross each other - adjust the outline.");
        return;
      }
      if (polygonArea(points) < 20_000) {
        toast("error", "The room needs to be at least 2 m².");
        return;
      }
      replaceVertices(points);
      setDraftPoints([]);
      setTool("select");
      toast("success", "Room updated. Doors and windows were reset - add them next.");
    },
    [replaceVertices, setTool, toast],
  );

  const openingFits = (wall: number, offset: number, width: number): boolean => {
    const len = wallLength(room, wall);
    if (offset < 0 || offset + width > len) return false;
    const spans = [
      ...room.doors.filter((d) => d.wall_index === wall).map((d) => [d.offset_cm, d.offset_cm + d.width_cm]),
      ...room.windows.filter((w) => w.wall_index === wall).map((w) => [w.offset_cm, w.offset_cm + w.width_cm]),
    ];
    return spans.every(([a, b]) => offset + width <= a || offset >= b);
  };

  // --- stage events per tool -----------------------------------------------------

  const onStageClick = (e: KonvaEventObject<MouseEvent | Event>) => {
    const stage = stageRef.current;
    if (!stage) return;
    const p = worldPointer();
    if (!p) return;

    if (tool === "select") {
      if (e.target === stage) {
        select(null);
        selectOpening(null);
        useUiStore.getState().setWarning(null);
      }
      return;
    }

    if (tool === "wall") {
      const last = draftPoints[draftPoints.length - 1] ?? null;
      const snapped = orthoSnap(p, last);
      if (draftPoints.length >= 3) {
        const [fx, fy] = draftPoints[0];
        if (Math.hypot(snapped[0] - fx, snapped[1] - fy) < closeRadius) {
          finishPolygon(draftPoints);
          return;
        }
      }
      if (last && Math.hypot(snapped[0] - last[0], snapped[1] - last[1]) < 1) return;
      setDraftPoints([...draftPoints, snapped]);
      return;
    }

    if (tool === "door" || tool === "window") {
      if (!openingGhost?.valid) return;
      const width = tool === "door" ? doorWidth : windowWidth;
      const id = `${tool}-${Date.now().toString(36)}`;
      if (tool === "door") {
        addDoor({ id, wall_index: openingGhost.wall, offset_cm: openingGhost.offset, width_cm: width, height_cm: 210, swing: "inward", hinge: "left" });
      } else {
        addWindow({ id, wall_index: openingGhost.wall, offset_cm: openingGhost.offset, width_cm: width, sill_height_cm: 90, height_cm: 120 });
      }
      selectOpening(id);
      setTool("select");
      return;
    }

    if (tool === "measure") {
      if (!measure || measure.frozen) {
        setMeasure({ a: p, b: null, frozen: false });
      } else {
        setMeasure({ ...measure, b: p, frozen: true });
      }
    }
  };

  const onStageMove = () => {
    const p = worldPointer();
    if (!p) return;
    if (tool === "wall") {
      const last = draftPoints[draftPoints.length - 1] ?? null;
      setCursor(orthoSnap(p, last));
    } else if (tool === "door" || tool === "window") {
      const width = tool === "door" ? doorWidth : windowWidth;
      const near = nearestWall(room, p);
      if (near.dist < 60) {
        const len = wallLength(room, near.wall);
        const offset = snapTo(Math.max(0, Math.min(len - width, near.offset - width / 2)), 5);
        setOpeningGhost({ wall: near.wall, offset, valid: openingFits(near.wall, offset, width) });
      } else {
        setOpeningGhost(null);
      }
    } else if (tool === "measure" && measure && !measure.frozen) {
      setMeasure({ ...measure, b: p, frozen: false });
    }
  };

  // tool changes reset transient drawing state (adjust-during-render pattern)
  const [prevTool, setPrevTool] = useState(tool);
  if (prevTool !== tool) {
    setPrevTool(tool);
    setDraftPoints([]);
    setOpeningGhost(null);
    setMeasure(null);
    setCursor(null);
  }
  useEffect(() => {
    stageRef.current?.draggable(tool === "select");
  }, [tool]);

  // --- keyboard -------------------------------------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) return;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      switch (e.key) {
        case "Escape":
          if (tool === "wall" && draftPoints.length) setDraftPoints([]);
          else if (tool !== "select") setTool("select");
          else {
            select(null);
            selectOpening(null);
            useUiStore.getState().setWarning(null);
            useUiStore.getState().setGhost(null);
          }
          break;
        case "Enter":
          if (tool === "wall" && draftPoints.length >= 3) finishPolygon(draftPoints);
          break;
        case "Delete":
        case "Backspace": {
          const ui = useUiStore.getState();
          if (ui.selectedId) {
            e.preventDefault();
            removeItem(ui.selectedId);
          } else if (ui.selectedOpeningId) {
            e.preventDefault();
            usePlannerStore.getState().removeOpening(ui.selectedOpeningId);
            selectOpening(null);
          }
          break;
        }
        case "v": case "V": setTool("select"); break;
        case "w": case "W": setTool("wall"); break;
        case "d": case "D": setTool("door"); break;
        case "n": case "N": setTool("window"); break;
        case "m": case "M": setTool("measure"); break;
        case "f": case "F": useUiStore.getState().requestFit(); break;
        case "+": case "=": useUiStore.getState().nudgeZoom(1); break;
        case "-": case "_": useUiStore.getState().nudgeZoom(-1); break;
        case "r": case "R": {
          const id = useUiStore.getState().selectedId;
          if (id) {
            const item = usePlannerStore.getState().items.find((i) => i.instance_id === id);
            if (item) {
              usePlannerStore.getState().moveItem(id, { rotation_deg: (item.rotation_deg + 90) % 360 });
              validateItemDebounced(id);
            }
          }
          break;
        }
        case "ArrowUp": case "ArrowDown": case "ArrowLeft": case "ArrowRight": {
          const id = useUiStore.getState().selectedId;
          if (!id) break;
          e.preventDefault();
          const item = usePlannerStore.getState().items.find((i) => i.instance_id === id);
          if (!item) break;
          const step = e.shiftKey ? 1 : 5;
          const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
          const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
          usePlannerStore.getState().moveItem(id, { x: item.x + dx, y: item.y + dy });
          validateItemDebounced(id);
          break;
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tool, draftPoints, finishPolygon, select, selectOpening, setTool]);

  // --- grid lines -------------------------------------------------------------------

  const grid = useMemo(() => {
    const bbox = roomBBox(room);
    const margin = 400;
    const x0 = Math.floor((bbox.minX - margin) / 100) * 100;
    const x1 = Math.ceil((bbox.minX + bbox.w + margin) / 100) * 100;
    const y0 = Math.floor((bbox.minY - margin) / 100) * 100;
    const y1 = Math.ceil((bbox.minY + bbox.h + margin) / 100) * 100;
    const minor: number[][] = [];
    const major: number[][] = [];
    const showMinor = scale * 50 > 14;
    for (let x = x0; x <= x1; x += 50) {
      (x % 100 === 0 ? major : showMinor ? minor : []).push([x, y0, x, y1]);
    }
    for (let y = y0; y <= y1; y += 50) {
      (y % 100 === 0 ? major : showMinor ? minor : []).push([x0, y, x1, y]);
    }
    return { minor, major };
  }, [room, scale]);

  const warningGeometry = warning?.result.findings.find((f) => f.geometry)?.geometry ?? null;
  const measureLen = measure?.b ? Math.hypot(measure.b[0] - measure.a[0], measure.b[1] - measure.a[1]) : 0;

  const cursorClass =
    tool === "select" ? "cursor-default" : tool === "measure" ? "cursor-crosshair" : "cursor-crosshair";

  return (
    <div ref={containerRef} className={`absolute inset-0 touch-none ${cursorClass}`}>
      <Stage
        ref={stageRef}
        width={size.w}
        height={size.h}
        draggable={tool === "select"}
        onWheel={onWheel}
        onClick={onStageClick}
        onTap={onStageClick}
        onMouseMove={onStageMove}
        onTouchMove={(e) => {
          onTouchMove(e);
          onStageMove();
        }}
        onTouchEnd={onTouchEnd}
        onDragEnd={() => { /* stage pan end */ }}
      >
        {/* decor-layer is hidden in AI-preview snapshots */}
        <Layer name="decor-layer" listening={false}>
          {grid.minor.map((pts, i) => (
            <Line key={`gm-${i}`} points={pts} stroke="#1C1917" strokeWidth={0.5 / scale} opacity={0.04} />
          ))}
          {grid.major.map((pts, i) => (
            <Line key={`gM-${i}`} points={pts} stroke="#1C1917" strokeWidth={0.7 / scale} opacity={0.08} />
          ))}
        </Layer>

        {/* fade the existing room while the Draw Wall tool is active, so the canvas
            reads as a fresh surface to draw a new room on (it's replaced on close) */}
        <Layer opacity={tool === "wall" ? 0.2 : 1}>
          <RoomShape scale={scale} interactive={tool === "select"} />
        </Layer>

        <Layer name="decor-layer" listening={false}>
          {overlaysVisible && analysis && <AnalysisOverlay analysis={analysis} scale={scale} />}
          {warningGeometry && <WarningGeometry polygon={warningGeometry} scale={scale} />}
        </Layer>

        <Layer>
          {/* rugs and other walkable items always render beneath furniture */}
          {[...items]
            .sort((a, b) => {
              const aw = productsById[a.product_id]?.is_walkable ? 0 : 1;
              const bw = productsById[b.product_id]?.is_walkable ? 0 : 1;
              return aw - bw;
            })
            .map((item) => {
              const product = productsById[item.product_id];
              if (!product) return null;
              return (
                <PlacedItemNode
                  key={item.instance_id}
                  item={item}
                  product={product}
                  selected={selectedId === item.instance_id}
                  scale={scale}
                  interactive={tool === "select"}
                />
              );
            })}
          {ghost && <GhostNode ghost={ghost} scale={scale} />}
        </Layer>

        {/* Assist-with-AI proposed layout: tap a ghost to accept just that item.
            Named "decor-layer" so pending ghosts are excluded from AI render
            snapshots (snapshotCanvas hides decor-layer); naming doesn't affect
            on-screen interactivity. */}
        {proposedItems.length > 0 && (
          <Layer name="decor-layer">
            {proposedItems.map((g) => {
              const product = productsById[g.product_id];
              if (!product) return null;
              return (
                <ProposedItemNode
                  key={g.instance_id}
                  item={g}
                  product={product}
                  scale={scale}
                  onAccept={() => acceptOne(g.instance_id)}
                />
              );
            })}
          </Layer>
        )}

        {/* transient tool previews */}
        <Layer name="decor-layer" listening={false}>
          {tool === "wall" && draftPoints.length > 0 && (
            <Group>
              <Line
                points={[...draftPoints.flat(), ...(cursor ?? draftPoints[draftPoints.length - 1])]}
                stroke="#1C1917"
                strokeWidth={3 / scale}
                dash={[10 / scale, 6 / scale]}
              />
              {draftPoints.map(([x, y], i) => (
                <Circle key={i} x={x} y={y} radius={(i === 0 ? 8 : 5) / scale} fill={i === 0 ? "#FDE9CC" : "#FFFFFF"} stroke="#1C1917" strokeWidth={1.5 / scale} />
              ))}
              {cursor && draftPoints.length > 0 && (
                <Label x={cursor[0]} y={cursor[1] - 16 / scale}>
                  <Tag fill="#1C1917" cornerRadius={4 / scale} />
                  <Text
                    text={`${(Math.hypot(cursor[0] - draftPoints[draftPoints.length - 1][0], cursor[1] - draftPoints[draftPoints.length - 1][1]) / 100).toFixed(2)} m`}
                    fontSize={11 / scale}
                    fill="#FAFAF8"
                    fontFamily="Inter, sans-serif"
                    padding={4 / scale}
                  />
                </Label>
              )}
            </Group>
          )}

          {(tool === "door" || tool === "window") && openingGhost && (
            <OpeningGhostPreview
              room={room}
              wall={openingGhost.wall}
              offset={openingGhost.offset}
              width={tool === "door" ? doorWidth : windowWidth}
              valid={openingGhost.valid}
            />
          )}

          {tool === "measure" && measure?.b && (
            <Group>
              <Line points={[...measure.a, ...measure.b]} stroke="#B45309" strokeWidth={1.6 / scale} dash={[8 / scale, 5 / scale]} />
              <Circle x={measure.a[0]} y={measure.a[1]} radius={4 / scale} fill="#B45309" />
              <Circle x={measure.b[0]} y={measure.b[1]} radius={4 / scale} fill="#B45309" />
              <Label x={(measure.a[0] + measure.b[0]) / 2} y={(measure.a[1] + measure.b[1]) / 2 - 12 / scale}>
                <Tag fill="#B45309" cornerRadius={4 / scale} />
                <Text text={`${(measureLen / 100).toFixed(2)} m`} fontSize={12 / scale} fill="#FFFFFF" fontFamily="Inter, sans-serif" padding={5 / scale} />
              </Label>
            </Group>
          )}
        </Layer>
      </Stage>

      {/* HTML overlay (renders above the canvas): Assist-with-AI button + controls */}
      <AssistPanel />
    </div>
  );
}

function OpeningGhostPreview({
  room,
  wall,
  offset,
  width,
  valid,
}: {
  room: { vertices: Point[] };
  wall: number;
  offset: number;
  width: number;
  valid: boolean;
}) {
  const n = room.vertices.length;
  const [ax, ay] = room.vertices[wall];
  const [bx, by] = room.vertices[(wall + 1) % n];
  const len = Math.hypot(bx - ax, by - ay) || 1;
  const dir = [(bx - ax) / len, (by - ay) / len];
  const p1: Point = [ax + dir[0] * offset, ay + dir[1] * offset];
  const p2: Point = [ax + dir[0] * (offset + width), ay + dir[1] * (offset + width)];
  return (
    <Line
      points={[...p1, ...p2]}
      stroke={valid ? "#15803D" : "#B91C1C"}
      strokeWidth={16}
      opacity={0.75}
      lineCap="butt"
    />
  );
}
