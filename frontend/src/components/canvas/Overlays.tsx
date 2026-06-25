"use client";

import { Group, Label, Line, Rect, Tag, Text } from "react-konva";
import { CATEGORY_LABELS, REASON_PHRASES } from "@/lib/constants";
import { useProduct } from "@/stores/productStore";
import type { AnalysisResponse, GhostPreviewPose, Point, Zone } from "@/types/overlays";
import type { PlacedItem, Product } from "@/types/api";
import { FurnitureGlyph } from "./FurnitureShape";
import { productFill } from "@/lib/constants";

function centroidTop(polygon: Point[]): Point {
  let cx = 0;
  let minY = Infinity;
  for (const [x, y] of polygon) {
    cx += x;
    minY = Math.min(minY, y);
  }
  return [cx / polygon.length, minY];
}

function centroid(polygon: Point[]): Point {
  let cx = 0;
  let cy = 0;
  for (const [x, y] of polygon) {
    cx += x;
    cy += y;
  }
  return [cx / polygon.length, cy / polygon.length];
}

/** Mockup parity: "Recommended placement" explanation card on the canvas. */
function PlacementCallout({ zone, scale }: { zone: Zone; scale: number }) {
  const phrases = zone.reason_codes.map((c) => REASON_PHRASES[c]).filter(Boolean).slice(0, 2);
  if (phrases.length === 0) return null;
  const body = `Placing the ${CATEGORY_LABELS[zone.category].toLowerCase()} here ${phrases.join(" and ")}.`;
  const [cx, cy] = centroid(zone.polygon);
  const w = 215 / scale;
  const titleSize = 11 / scale;
  const bodySize = 10 / scale;
  const pad = 9 / scale;
  const bodyHeight = bodySize * 1.35 * Math.ceil((body.length * bodySize * 0.52) / (w - pad * 2));
  const h = pad * 2 + titleSize + 5 / scale + bodyHeight;
  return (
    <Group x={cx - w / 2} y={cy - h / 2} listening={false}>
      <Rect width={w} height={h} fill="#FFFFFF" cornerRadius={8 / scale} shadowColor="#1C1917" shadowBlur={12 / scale} shadowOpacity={0.18} />
      <Text x={pad} y={pad} text="Recommended placement" fontSize={titleSize} fontStyle="700" fontFamily="Inter, sans-serif" fill="#1C1917" />
      <Text
        x={pad}
        y={pad + titleSize + 5 / scale}
        width={w - pad * 2}
        text={body}
        fontSize={bodySize}
        lineHeight={1.35}
        fontFamily="Inter, sans-serif"
        fill="#57534E"
      />
    </Group>
  );
}

export function ZonesOverlay({
  zones,
  scale,
  calloutVisible = false,
}: {
  zones: Zone[];
  scale: number;
  calloutVisible?: boolean;
}) {
  return (
    <Group listening={false}>
      {zones.map((zone) => {
        const [lx, ly] = centroidTop(zone.polygon);
        const reason = zone.reason_codes.map((c) => REASON_PHRASES[c]).find(Boolean);
        const label =
          zone.rank === 0
            ? `Best spot for ${CATEGORY_LABELS[zone.category].toLowerCase()}${reason ? ` · ${reason}` : ""}`
            : `Option ${zone.rank + 1}`;
        return (
          <Group key={zone.id}>
            <Line
              points={zone.polygon.flat()}
              closed
              stroke={zone.rank === 0 ? "#D97706" : "#D6C9B4"}
              strokeWidth={1.8 / scale}
              dash={[10 / scale, 6 / scale]}
              fill={zone.rank === 0 ? "rgba(217,119,6,0.10)" : "rgba(214,201,180,0.14)"}
            />
            {zone.rank === 0 && (
              <Label x={lx} y={ly - 8 / scale}>
                <Tag
                  fill="#FDE9CC"
                  stroke="#D97706"
                  strokeWidth={1 / scale}
                  cornerRadius={9 / scale}
                  pointerDirection="down"
                  pointerWidth={8 / scale}
                  pointerHeight={5 / scale}
                />
                <Text
                  text={label}
                  fontSize={11 / scale}
                  fontStyle="600"
                  fontFamily="Inter, sans-serif"
                  fill="#92400E"
                  padding={6 / scale}
                />
              </Label>
            )}
            {zone.rank === 0 && calloutVisible && <PlacementCallout zone={zone} scale={scale} />}
          </Group>
        );
      })}
    </Group>
  );
}

export function AnalysisOverlay({ analysis, scale }: { analysis: AnalysisResponse; scale: number }) {
  return (
    <Group listening={false}>
      {analysis.corridors.map((corridor) => (
        <Line
          key={corridor.id}
          points={corridor.polygon.flat()}
          closed
          fill="rgba(181,164,139,0.32)"
          stroke="#A8967A"
          strokeWidth={1.5 / scale}
          dash={[7 / scale, 5 / scale]}
        />
      ))}
      {analysis.keep_clear.map((poly, i) => (
        <Line
          key={`kc-${i}`}
          points={poly.flat()}
          closed
          fill="rgba(194,65,12,0.16)"
          stroke="#C2410C"
          strokeWidth={1.5 / scale}
          dash={[5 / scale, 4 / scale]}
        />
      ))}
      {analysis.window_strips.map((poly, i) => (
        <Line
          key={`ws-${i}`}
          points={poly.flat()}
          closed
          fill="rgba(217,119,6,0.14)"
          stroke="#D97706"
          strokeWidth={1 / scale}
          dash={[4 / scale, 4 / scale]}
        />
      ))}
    </Group>
  );
}

export function WarningGeometry({ polygon, scale }: { polygon: Point[]; scale: number }) {
  return (
    <Line
      points={polygon.flat()}
      closed
      fill="rgba(185,28,28,0.10)"
      stroke="#B91C1C"
      strokeWidth={1.6 / scale}
      dash={[8 / scale, 5 / scale]}
      listening={false}
    />
  );
}

/** A single "Assist with AI" suggestion: semi-transparent furniture the user can
 *  tap to commit. Not interactive-draggable - acceptance turns it into a real item. */
export function ProposedItemNode({
  item,
  product,
  scale,
  onAccept,
}: {
  item: PlacedItem;
  product: Product;
  scale: number;
  onAccept: () => void;
}) {
  const w = product.width_cm;
  const d = product.depth_cm;
  const setCursor = (cur: string) => (e: { target: { getStage: () => { container: () => HTMLElement } | null } }) => {
    const stage = e.target.getStage();
    if (stage) stage.container().style.cursor = cur;
  };
  return (
    <Group
      x={item.x}
      y={item.y}
      rotation={item.rotation_deg}
      opacity={0.5}
      onClick={(e) => {
        e.cancelBubble = true;
        onAccept();
      }}
      onTap={(e) => {
        e.cancelBubble = true;
        onAccept();
      }}
      onMouseEnter={setCursor("pointer")}
      onMouseLeave={setCursor("default")}
    >
      <FurnitureGlyph product={product} fill={productFill(product.colors)} />
      <Line
        points={[-w / 2 - 6, -d / 2 - 6, w / 2 + 6, -d / 2 - 6, w / 2 + 6, d / 2 + 6, -w / 2 - 6, d / 2 + 6]}
        closed
        stroke="#B45309"
        strokeWidth={2 / scale}
        dash={[8 / scale, 5 / scale]}
      />
      <Label y={-d / 2 - 18 / scale}>
        <Tag fill="#B45309" cornerRadius={5 / scale} pointerDirection="down" pointerWidth={7 / scale} pointerHeight={4 / scale} />
        <Text text="Tap to add" fontSize={11 / scale} fontFamily="Inter, sans-serif" fill="#FFFFFF" padding={5 / scale} />
      </Label>
    </Group>
  );
}

export function GhostNode({ ghost, scale }: { ghost: GhostPreviewPose; scale: number }) {
  const product = useProduct(ghost.productId);
  if (!product) return null;
  return (
    <Group
      x={ghost.pose.x}
      y={ghost.pose.y}
      rotation={ghost.pose.rotation_deg}
      opacity={0.55}
      listening={false}
    >
      <FurnitureGlyph product={product} fill={productFill(product.colors)} />
      <Line
        points={[
          -product.width_cm / 2 - 6, -product.depth_cm / 2 - 6,
          product.width_cm / 2 + 6, -product.depth_cm / 2 - 6,
          product.width_cm / 2 + 6, product.depth_cm / 2 + 6,
          -product.width_cm / 2 - 6, product.depth_cm / 2 + 6,
        ]}
        closed
        stroke="#15803D"
        strokeWidth={2 / scale}
        dash={[8 / scale, 5 / scale]}
      />
      <Label y={-product.depth_cm / 2 - 18 / scale}>
        <Tag fill="#15803D" cornerRadius={5 / scale} pointerDirection="down" pointerWidth={7 / scale} pointerHeight={4 / scale} />
        <Text
          text={ghost.label}
          fontSize={11 / scale}
          fontFamily="Inter, sans-serif"
          fill="#FFFFFF"
          padding={5 / scale}
        />
      </Label>
    </Group>
  );
}
