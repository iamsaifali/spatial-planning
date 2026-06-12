"use client";

/** Parameterized 3D furniture built from product dimensions (mock products now;
 *  real ones later will slot in unchanged). Local space: centred at origin,
 *  width along x, depth along z, front facing +z - matching the 2D convention. */

import { productFill } from "@/lib/constants";
import { CM } from "@/lib/scene3d";
import type { PlacedItem, Product } from "@/types/api";

function darken(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * (1 - amount));
  const g = Math.round(((n >> 8) & 255) * (1 - amount));
  const b = Math.round((n & 255) * (1 - amount));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

function Sofa({ w, d, h, color, seatH, armH }: { w: number; d: number; h: number; color: string; seatH: number; armH: number }) {
  const arm = Math.min(w * 0.12, 0.22);
  const backD = Math.min(d * 0.25, 0.26);
  const innerW = w - arm * 2;
  return (
    <group>
      <mesh position={[0, seatH / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, seatH, d]} />
        <meshStandardMaterial color={color} roughness={0.9} />
      </mesh>
      <mesh position={[0, seatH + (h - seatH) / 2, -(d - backD) / 2]} castShadow>
        <boxGeometry args={[w, h - seatH, backD]} />
        <meshStandardMaterial color={darken(color, 0.08)} roughness={0.9} />
      </mesh>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[s * (w - arm) / 2, armH / 2, 0]} castShadow>
          <boxGeometry args={[arm, armH, d]} />
          <meshStandardMaterial color={darken(color, 0.06)} roughness={0.9} />
        </mesh>
      ))}
      {/* seat cushions */}
      {Array.from({ length: w > 2 ? 3 : 2 }, (_, i) => {
        const count = w > 2 ? 3 : 2;
        const cw = innerW / count - 0.02;
        const x = -innerW / 2 + (innerW / count) * (i + 0.5);
        return (
          <mesh key={i} position={[x, seatH + 0.05, (d - backD) / 2 - d / 2 + 0.02]} castShadow>
            <boxGeometry args={[cw, 0.1, d - backD - 0.06]} />
            <meshStandardMaterial color={darken(color, 0.03)} roughness={0.95} />
          </mesh>
        );
      })}
    </group>
  );
}

function Table({ w, d, h, color, round }: { w: number; d: number; h: number; color: string; round: boolean }) {
  const top = 0.035;
  const legColor = darken(color, 0.25);
  return (
    <group>
      {round ? (
        <mesh position={[0, h - top / 2, 0]} castShadow receiveShadow>
          <cylinderGeometry args={[w / 2, w / 2, top, 28]} />
          <meshStandardMaterial color={color} roughness={0.6} />
        </mesh>
      ) : (
        <mesh position={[0, h - top / 2, 0]} castShadow receiveShadow>
          <boxGeometry args={[w, top, d]} />
          <meshStandardMaterial color={color} roughness={0.6} />
        </mesh>
      )}
      {round ? (
        <mesh position={[0, (h - top) / 2, 0]} castShadow>
          <cylinderGeometry args={[0.04, 0.06, h - top, 12]} />
          <meshStandardMaterial color={legColor} roughness={0.7} />
        </mesh>
      ) : (
        [-1, 1].flatMap((sx) =>
          [-1, 1].map((sz) => (
            <mesh key={`${sx}${sz}`} position={[sx * (w / 2 - 0.05), (h - top) / 2, sz * (d / 2 - 0.05)]} castShadow>
              <boxGeometry args={[0.05, h - top, 0.05]} />
              <meshStandardMaterial color={legColor} roughness={0.7} />
            </mesh>
          )),
        )
      )}
    </group>
  );
}

function TvUnit({ w, d, h, color }: { w: number; d: number; h: number; color: string }) {
  const tvW = Math.min(w * 0.75, 1.65);
  const tvH = tvW * 0.56;
  return (
    <group>
      <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial color={color} roughness={0.6} />
      </mesh>
      {/* screen standing on the cabinet, against its back edge */}
      <mesh position={[0, h + tvH / 2 + 0.02, -d / 2 + 0.03]} castShadow>
        <boxGeometry args={[tvW, tvH, 0.04]} />
        <meshStandardMaterial color="#1c1917" roughness={0.3} metalness={0.4} />
      </mesh>
    </group>
  );
}

function Lamp({ w, h, color }: { w: number; h: number; color: string }) {
  return (
    <group>
      <mesh position={[0, 0.015, 0]} castShadow>
        <cylinderGeometry args={[w / 2.6, w / 2.4, 0.03, 20]} />
        <meshStandardMaterial color={darken(color, 0.3)} roughness={0.5} />
      </mesh>
      <mesh position={[0, h * 0.45, 0]}>
        <cylinderGeometry args={[0.012, 0.012, h * 0.84, 8]} />
        <meshStandardMaterial color={darken(color, 0.35)} roughness={0.5} metalness={0.3} />
      </mesh>
      <mesh position={[0, h * 0.88, 0]} castShadow>
        <cylinderGeometry args={[w / 2.4, w / 1.9, h * 0.22, 20, 1, true]} />
        <meshStandardMaterial color={color} roughness={0.9} side={2} />
      </mesh>
      <pointLight position={[0, h * 0.82, 0]} intensity={0.5} distance={3.2} color="#ffe7c2" />
    </group>
  );
}

function Plant({ w, h }: { w: number; h: number }) {
  const potH = Math.min(h * 0.3, 0.45);
  return (
    <group>
      <mesh position={[0, potH / 2, 0]} castShadow>
        <cylinderGeometry args={[w / 2.6, w / 3.2, potH, 16]} />
        <meshStandardMaterial color="#B5765A" roughness={0.85} />
      </mesh>
      {[[0, 0.78, 0], [0.16, 0.62, 0.1], [-0.14, 0.66, -0.08]].map(([x, f, z], i) => (
        <mesh key={i} position={[x * w, h * f, z * w]} castShadow>
          <sphereGeometry args={[w * (0.42 - i * 0.07), 12, 10]} />
          <meshStandardMaterial color={i % 2 ? "#5F7350" : "#6c8159"} roughness={0.95} />
        </mesh>
      ))}
    </group>
  );
}

function Chair({ w, d, h, color, seatH }: { w: number; d: number; h: number; color: string; seatH: number }) {
  const backD = Math.min(d * 0.22, 0.16);
  return (
    <group>
      <mesh position={[0, seatH / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, seatH, d]} />
        <meshStandardMaterial color={color} roughness={0.9} />
      </mesh>
      <mesh position={[0, seatH + (h - seatH) / 2, -(d - backD) / 2]} castShadow>
        <boxGeometry args={[w, h - seatH, backD]} />
        <meshStandardMaterial color={darken(color, 0.08)} roughness={0.9} />
      </mesh>
    </group>
  );
}

function Storage({ w, d, h, color }: { w: number; d: number; h: number; color: string }) {
  return (
    <group>
      <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial color={color} roughness={0.65} />
      </mesh>
      <mesh position={[0, h / 2, d / 2 + 0.002]}>
        <boxGeometry args={[w - 0.04, h - 0.04, 0.004]} />
        <meshStandardMaterial color={darken(color, 0.12)} roughness={0.7} />
      </mesh>
    </group>
  );
}

export function Furniture3D({ item, product }: { item: PlacedItem; product: Product }) {
  const w = product.width_cm * CM;
  const d = product.depth_cm * CM;
  const h = product.height_cm * CM;
  const color = product.category === "custom" ? "#B8B2A9" : productFill(product.colors);
  const seatH = (product.attrs?.seat_height_cm ?? 43) * CM;
  const armH = (product.attrs?.arm_height_cm ?? 60) * CM;

  let body: React.ReactNode;
  switch (product.category) {
    case "sofa":
      body = <Sofa w={w} d={d} h={h} color={color} seatH={seatH} armH={armH} />;
      break;
    case "rug":
      body = (
        <mesh position={[0, 0.006, 0]} receiveShadow>
          <boxGeometry args={[w, 0.012, d]} />
          <meshStandardMaterial color={color} roughness={1} />
        </mesh>
      );
      break;
    case "coffee_table":
    case "side_table":
      body = <Table w={w} d={d} h={h} color={color} round={product.shape === "round"} />;
      break;
    case "tv_unit":
      body = <TvUnit w={w} d={d} h={h} color={color} />;
      break;
    case "accent_chair":
      body = <Chair w={w} d={d} h={h} color={color} seatH={seatH} />;
      break;
    case "lighting":
      body = <Lamp w={w} h={h} color={color} />;
      break;
    case "storage":
      body = <Storage w={w} d={d} h={h} color={color} />;
      break;
    case "decor":
      body = <Plant w={w} h={h} />;
      break;
    default:
      body = (
        <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
          <boxGeometry args={[w, h, d]} />
          <meshStandardMaterial color={color} roughness={0.8} />
        </mesh>
      );
  }

  return (
    <group
      position={[item.x * CM, 0, item.y * CM]}
      rotation={[0, -(item.rotation_deg * Math.PI) / 180, 0]}
    >
      {body}
    </group>
  );
}
