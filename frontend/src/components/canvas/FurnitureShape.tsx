"use client";

/** Parameterized top-view furniture drawings (Konva primitives, cm units).
 *  Local origin = footprint center; width along +x, front faces +y.
 */

import { useEffect, useState } from "react";
import { Circle, Ellipse, Group, Image as KonvaImage, Line, Rect } from "react-konva";
import type { Product } from "@/types/api";

/** Route an icon through our same-origin proxy so drawing it on the canvas doesn't taint
 *  it (the bucket has no CORS) - which would otherwise break the AI-preview export. */
function iconSrc(url: string): string {
  return `/api/icon?u=${encodeURIComponent(url)}`;
}

/** Load an <img> for Konva (client-only). crossOrigin="anonymous" + the proxy's CORS
 *  header keep the canvas clean/exportable. */
function useHtmlImage(src?: string): HTMLImageElement | null {
  // keyed by src so a stale load never shows on a changed/cleared src (and we never
  // call setState synchronously in the effect - only in the async onload callback)
  const [loaded, setLoaded] = useState<{ src: string; img: HTMLImageElement } | null>(null);
  useEffect(() => {
    if (!src) return;
    const im = new window.Image();
    im.crossOrigin = "anonymous";
    let alive = true;
    im.onload = () => {
      if (alive) setLoaded({ src, img: im });
    };
    im.src = src;
    return () => {
      alive = false;
    };
  }, [src]);
  return loaded && loaded.src === src ? loaded.img : null;
}

/** Render the product's real top-down icon as a "sticker" at its footprint; fall back to
 *  the parametric glyph while the image loads or when the product has no icon. */
export function FurnitureSprite({ product, fill }: { product: Product; fill: string }) {
  const img = useHtmlImage(product.two_d_icon ? iconSrc(product.two_d_icon) : undefined);
  if (product.two_d_icon && img) {
    const w = product.width_cm;
    const d = product.depth_cm;
    return <KonvaImage image={img} x={-w / 2} y={-d / 2} width={w} height={d} listening={false} />;
  }
  return <FurnitureGlyph product={product} fill={fill} />;
}

function darken(hex: string, amount = 0.22): string {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * (1 - amount));
  const g = Math.round(((n >> 8) & 255) * (1 - amount));
  const b = Math.round((n & 255) * (1 - amount));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

export function FurnitureGlyph({ product, fill }: { product: Product; fill: string }) {
  const w = product.width_cm;
  const d = product.depth_cm;
  const stroke = darken(fill);
  const round = product.shape === "round";

  switch (product.category) {
    case "sofa": {
      const arm = Math.min(w * 0.11, 22);
      const back = Math.min(d * 0.28, 26);
      const cushions = w >= 200 ? 3 : 2;
      const innerW = w - arm * 2;
      return (
        <Group>
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={10} fill={fill} stroke={stroke} strokeWidth={1.5} />
          {/* back rest along the rear edge (front faces +y) */}
          <Rect x={-w / 2 + 3} y={-d / 2 + 3} width={w - 6} height={back} cornerRadius={6} fill={darken(fill, 0.1)} />
          <Rect x={-w / 2 + 3} y={-d / 2 + 3} width={arm} height={d - 6} cornerRadius={6} fill={darken(fill, 0.08)} />
          <Rect x={w / 2 - arm - 3} y={-d / 2 + 3} width={arm} height={d - 6} cornerRadius={6} fill={darken(fill, 0.08)} />
          {Array.from({ length: cushions - 1 }, (_, i) => {
            const x = -innerW / 2 + (innerW * (i + 1)) / cushions;
            return <Line key={i} points={[x, -d / 2 + back + 4, x, d / 2 - 5]} stroke={darken(fill, 0.12)} strokeWidth={1.2} />;
          })}
        </Group>
      );
    }
    case "rug":
      return (
        <Group>
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={4} fill={fill} opacity={0.85} stroke={stroke} strokeWidth={1.2} />
          <Rect x={-w / 2 + 9} y={-d / 2 + 9} width={w - 18} height={d - 18} cornerRadius={3} stroke={darken(fill, 0.15)} strokeWidth={1} />
          <Rect x={-w / 2 + 18} y={-d / 2 + 18} width={w - 36} height={d - 36} cornerRadius={2} stroke={darken(fill, 0.1)} strokeWidth={0.8} />
        </Group>
      );
    case "coffee_table":
    case "side_table": {
      if (round) {
        return (
          <Group>
            <Ellipse radiusX={w / 2} radiusY={d / 2} fill={fill} stroke={stroke} strokeWidth={1.5} />
            <Ellipse radiusX={w / 2 - 7} radiusY={d / 2 - 7} stroke={darken(fill, 0.12)} strokeWidth={1} />
          </Group>
        );
      }
      return (
        <Group>
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={6} fill={fill} stroke={stroke} strokeWidth={1.5} />
          <Rect x={-w / 2 + 6} y={-d / 2 + 6} width={w - 12} height={d - 12} cornerRadius={4} stroke={darken(fill, 0.12)} strokeWidth={1} />
        </Group>
      );
    }
    case "bed": {
      const headboard = Math.min(d * 0.1, 16);
      const pillowH = Math.min(d * 0.2, 38);
      const pillows = w >= 150 ? 2 : 1;
      const gap = 10;
      const pillowW = (w - 24 - gap * (pillows - 1)) / pillows;
      return (
        <Group>
          {/* mattress */}
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={8} fill={fill} stroke={stroke} strokeWidth={1.5} />
          {/* headboard along the back edge (-y, against the wall) */}
          <Rect x={-w / 2} y={-d / 2} width={w} height={headboard} cornerRadius={6} fill={darken(fill, 0.16)} />
          {/* duvet covering the lower ~55% */}
          <Rect x={-w / 2 + 4} y={-d / 2 + d * 0.42} width={w - 8} height={d * 0.55} cornerRadius={6} fill={darken(fill, 0.06)} />
          <Line points={[-w / 2 + 6, -d / 2 + d * 0.42, w / 2 - 6, -d / 2 + d * 0.42]} stroke={darken(fill, 0.12)} strokeWidth={1} />
          {/* pillows near the headboard */}
          {Array.from({ length: pillows }, (_, i) => (
            <Rect
              key={i}
              x={-w / 2 + 12 + i * (pillowW + gap)}
              y={-d / 2 + headboard + 6}
              width={pillowW}
              height={pillowH}
              cornerRadius={7}
              fill="#F4EEE2"
              stroke={darken(fill, 0.1)}
              strokeWidth={0.8}
            />
          ))}
        </Group>
      );
    }
    case "tv_unit":
      return (
        <Group>
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={4} fill={fill} stroke={stroke} strokeWidth={1.5} />
          <Line points={[-w / 2 + 8, 0, w / 2 - 8, 0]} stroke={darken(fill, 0.15)} strokeWidth={1} />
          {/* TV screen hint on the front edge */}
          <Rect x={-Math.min(w * 0.35, 60)} y={d / 2 - 6} width={Math.min(w * 0.7, 120)} height={4} cornerRadius={2} fill="#3A3531" />
        </Group>
      );
    case "accent_chair": {
      const back = Math.min(d * 0.24, 16);
      return (
        <Group>
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={12} fill={fill} stroke={stroke} strokeWidth={1.5} />
          <Rect x={-w / 2 + 3} y={-d / 2 + 3} width={w - 6} height={back} cornerRadius={8} fill={darken(fill, 0.1)} />
          <Rect x={-w / 2 + 5} y={-d / 2 + back + 6} width={w - 10} height={d - back - 12} cornerRadius={8} fill={darken(fill, 0.04)} />
        </Group>
      );
    }
    case "lighting":
      return (
        <Group>
          <Circle radius={w / 2} fill={fill} opacity={0.55} stroke={stroke} strokeWidth={1.2} />
          <Circle radius={w / 5} fill={darken(fill, 0.2)} />
          <Circle radius={w / 2 - 4} stroke={darken(fill, 0.12)} strokeWidth={0.8} />
        </Group>
      );
    case "storage": {
      const sections = Math.max(2, Math.round(w / 45));
      return (
        <Group>
          <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={3} fill={fill} stroke={stroke} strokeWidth={1.5} />
          {Array.from({ length: sections - 1 }, (_, i) => {
            const x = -w / 2 + (w * (i + 1)) / sections;
            return <Line key={i} points={[x, -d / 2 + 3, x, d / 2 - 3]} stroke={darken(fill, 0.14)} strokeWidth={1} />;
          })}
          <Line points={[-w / 2 + 4, d / 2 - 5, w / 2 - 4, d / 2 - 5]} stroke={darken(fill, 0.1)} strokeWidth={0.8} />
        </Group>
      );
    }
    case "decor":
      return (
        <Group>
          <Circle radius={w / 2} fill={fill} stroke={stroke} strokeWidth={1.2} />
          <Circle x={-w / 6} y={-w / 7} radius={w / 4.2} fill={darken(fill, 0.12)} opacity={0.8} />
          <Circle x={w / 6} y={w / 8} radius={w / 4.8} fill={darken(fill, 0.06)} opacity={0.8} />
          <Circle x={w / 7} y={-w / 5} radius={w / 6} fill={darken(fill, 0.18)} opacity={0.7} />
        </Group>
      );
    default:
      return <Rect x={-w / 2} y={-d / 2} width={w} height={d} cornerRadius={6} fill={fill} stroke={stroke} strokeWidth={1.5} />;
  }
}
