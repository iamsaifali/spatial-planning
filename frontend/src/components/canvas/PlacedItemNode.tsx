"use client";

import type Konva from "konva";
import { useRef, useState } from "react";
import { Circle, Group, Label, Line, Rect, Tag, Text } from "react-konva";
import { rectInsidePolygon, rectsOverlap, type Rect as GRect } from "@/lib/geometry";
import { productFill } from "@/lib/constants";
import { formatDims } from "@/lib/format";
import { validateItemDebounced } from "@/lib/placement";
import { plannerTemporal, usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";
import type { PlacedItem, Product } from "@/types/api";
import { FurnitureGlyph } from "./FurnitureShape";

function snapAngle(deg: number, step = 15): number {
  return ((Math.round(deg / step) * step) % 360 + 360) % 360;
}

export function PlacedItemNode({
  item,
  product,
  selected,
  scale,
  interactive,
}: {
  item: PlacedItem;
  product: Product;
  selected: boolean;
  scale: number;
  interactive: boolean;
}) {
  const groupRef = useRef<Konva.Group>(null);
  const [dragInvalid, setDragInvalid] = useState(false);
  const [liveRotation, setLiveRotation] = useState<number | null>(null);

  const select = useUiStore((s) => s.select);
  const moveItem = usePlannerStore((s) => s.moveItem);
  const issueLevel = useUiStore((s) => s.itemIssues[item.instance_id]);

  const w = product.width_cm;
  const d = product.depth_cm;
  const fill = productFill(product.colors);
  const px = (v: number) => v / scale; // screen-constant size in world units

  const checkAdvisory = (x: number, y: number, rot: number): boolean => {
    const { room, items } = usePlannerStore.getState();
    const products = useProductStore.getState().byId;
    const me: GRect = { cx: x, cy: y, w, d, rot };
    if (!rectInsidePolygon(me, room.vertices, 3)) return true;
    if (product.is_walkable) return false;
    for (const other of items) {
      if (other.instance_id === item.instance_id) continue;
      const op = products[other.product_id];
      if (!op || op.is_walkable) continue;
      if (rectsOverlap(me, { cx: other.x, cy: other.y, w: op.width_cm, d: op.depth_cm, rot: other.rotation_deg })) {
        return true;
      }
    }
    return false;
  };

  const commitPose = (x: number, y: number, rot: number) => {
    plannerTemporal.getState().resume();
    moveItem(item.instance_id, { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, rotation_deg: rot });
    setDragInvalid(false);
    validateItemDebounced(item.instance_id);
  };

  const rotation = liveRotation ?? item.rotation_deg;
  const showOutline = selected || dragInvalid;

  return (
    <Group
      ref={groupRef}
      x={item.x}
      y={item.y}
      rotation={rotation}
      draggable={interactive}
      listening={interactive}
      onClick={(e) => {
        e.cancelBubble = true;
        select(item.instance_id);
      }}
      onTap={(e) => {
        e.cancelBubble = true;
        select(item.instance_id);
      }}
      onDragStart={(e) => {
        e.cancelBubble = true;
        select(item.instance_id);
        plannerTemporal.getState().pause();
        useUiStore.getState().setWarning(null);
      }}
      onDragMove={(e) => {
        const node = e.target;
        setDragInvalid(checkAdvisory(node.x(), node.y(), node.rotation()));
      }}
      onDragEnd={(e) => {
        commitPose(e.target.x(), e.target.y(), e.target.rotation());
      }}
      opacity={product.is_walkable ? 0.96 : 1}
    >
      {/* soft contact shadow */}
      {!product.is_walkable && (
        <Rect
          x={-w / 2 + 3}
          y={-d / 2 + 5}
          width={w}
          height={d}
          cornerRadius={10}
          fill="#1C1917"
          opacity={0.07}
        />
      )}
      <FurnitureGlyph product={product} fill={fill} />
      {issueLevel && !selected && (
        <Circle
          x={w / 2 - px(4)}
          y={-d / 2 + px(4)}
          radius={px(5)}
          fill={issueLevel === "error" ? "#B91C1C" : "#C2410C"}
          stroke="#FFFFFF"
          strokeWidth={px(1.5)}
          listening={false}
        />
      )}

      {showOutline && (
        <Rect
          x={-w / 2 - 4}
          y={-d / 2 - 4}
          width={w + 8}
          height={d + 8}
          cornerRadius={8}
          stroke={dragInvalid ? "#B91C1C" : "#B45309"}
          dash={[8, 5]}
          strokeWidth={px(1.6)}
          listening={false}
        />
      )}

      {selected && interactive && (
        <>
          {/* rotation handle above the back edge */}
          <Line
            points={[0, -d / 2 - 4, 0, -d / 2 - px(26)]}
            stroke="#B45309"
            strokeWidth={px(1.2)}
            listening={false}
          />
          <Circle
            y={-d / 2 - px(34)}
            radius={px(9)}
            fill="#FDE9CC"
            stroke="#B45309"
            strokeWidth={px(1.4)}
            draggable
            onDragStart={(e) => {
              e.cancelBubble = true;
              plannerTemporal.getState().pause();
            }}
            onDragMove={(e) => {
              e.cancelBubble = true;
              const group = groupRef.current;
              if (!group) return;
              const stage = group.getStage();
              const pointer = stage?.getRelativePointerPosition();
              if (!pointer) return;
              const angle = (Math.atan2(pointer.y - group.y(), pointer.x - group.x()) * 180) / Math.PI + 90;
              setLiveRotation(snapAngle(angle));
              // keep the handle pinned; rotation comes from the group
              e.target.position({ x: 0, y: -d / 2 - px(34) });
            }}
            onDragEnd={(e) => {
              e.cancelBubble = true;
              const rot = liveRotation ?? item.rotation_deg;
              setLiveRotation(null);
              commitPose(item.x, item.y, rot);
            }}
          />
          <Label x={0} y={d / 2 + px(12)} listening={false}>
            <Tag fill="#1C1917" cornerRadius={px(5)} pointerDirection="up" pointerHeight={px(5)} pointerWidth={px(8)} />
            <Text
              text={`${product.name}  ·  ${formatDims(w, d)}`}
              fontSize={px(11)}
              fontFamily="Inter, sans-serif"
              fill="#FAFAF8"
              padding={px(6)}
            />
          </Label>
        </>
      )}
    </Group>
  );
}
