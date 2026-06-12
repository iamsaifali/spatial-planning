"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { buildWalls, CM, roomCenter, roomRadius } from "@/lib/scene3d";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useSceneStore } from "@/stores/sceneStore";
import { Furniture3D } from "./Furniture3D";

const COLORS = {
  floor: "#D8C6A6",
  wall: "#F2EEE7",
  wallTop: "#E5DFD4",
  glass: "#CFE3DD",
  ground: "#EFEBE3",
};

function Floor() {
  const room = usePlannerStore((s) => s.room);
  const shape = useMemo(() => {
    const s = new THREE.Shape();
    room.vertices.forEach(([x, y], i) => {
      if (i === 0) s.moveTo(x * CM, y * CM);
      else s.lineTo(x * CM, y * CM);
    });
    s.closePath();
    return s;
  }, [room.vertices]);

  return (
    <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
      <shapeGeometry args={[shape]} />
      <meshStandardMaterial color={COLORS.floor} roughness={0.85} side={THREE.DoubleSide} />
    </mesh>
  );
}

function Walls() {
  const room = usePlannerStore((s) => s.room);
  const thicknessCm = useSceneStore((s) => s.wallThicknessCm);
  const { boxes, glass, walls } = useMemo(() => buildWalls(room), [room]);
  const t = thicknessCm * CM;
  const wallGroups = useRef<(THREE.Group | null)[]>([]);

  // dollhouse effect: hide any wall the camera is looking at from OUTSIDE,
  // so the interior always stays visible while orbiting
  useFrame(({ camera }) => {
    walls.forEach((meta, i) => {
      const group = wallGroups.current[i];
      if (!group || !meta) return;
      const toCam = [camera.position.x - meta.mid[0], camera.position.z - meta.mid[1]];
      const len = Math.hypot(toCam[0], toCam[1]) || 1;
      const facing = (toCam[0] / len) * meta.outward[0] + (toCam[1] / len) * meta.outward[1];
      group.visible = facing < 0.12;
    });
  });

  return (
    <group>
      {walls.map((_, i) => (
        <group
          key={`wall-${i}`}
          ref={(el) => {
            wallGroups.current[i] = el;
          }}
        >
          {boxes
            .filter((box) => box.wall === i)
            .map((box) => (
              <mesh
                key={box.key}
                position={box.center}
                rotation={[0, box.rotationY, 0]}
                castShadow
                receiveShadow
              >
                <boxGeometry args={[box.size[0], box.size[1], t]} />
                <meshStandardMaterial
                  color={box.kind === "wall" ? COLORS.wall : COLORS.wallTop}
                  roughness={0.95}
                />
              </mesh>
            ))}
          {glass
            .filter((pane) => pane.wall === i)
            .map((pane) => (
              <mesh key={pane.key} position={pane.center} rotation={[0, pane.rotationY, 0]}>
                <boxGeometry args={pane.size} />
                <meshStandardMaterial color={COLORS.glass} transparent opacity={0.28} roughness={0.1} metalness={0.1} />
              </mesh>
            ))}
        </group>
      ))}
    </group>
  );
}

function Items() {
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);
  return (
    <group>
      {items.map((item) => {
        const product = byId[item.product_id];
        if (!product) return null;
        return <Furniture3D key={item.instance_id} item={item} product={product} />;
      })}
    </group>
  );
}

export default function Scene3D() {
  const room = usePlannerStore((s) => s.room);
  const [cx, cz] = roomCenter(room);
  const radius = roomRadius(room);
  const wallH = room.wall_height_cm * CM;

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{
        position: [cx + radius * 0.85, wallH * 2.4, cz + radius * 1.1],
        fov: 45,
        near: 0.1,
        far: 80,
      }}
      style={{ touchAction: "none" }}
    >
      <color attach="background" args={[COLORS.ground]} />
      <hemisphereLight args={["#fff8ec", "#cfc7b8", 0.75]} />
      <directionalLight
        position={[cx + radius, wallH * 4.2, cz - radius]}
        intensity={1.15}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-radius * 1.6}
        shadow-camera-right={radius * 1.6}
        shadow-camera-top={radius * 1.6}
        shadow-camera-bottom={-radius * 1.6}
      />
      {/* soft ground plane catching shadows outside the room */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[cx, -0.01, cz]} receiveShadow>
        <planeGeometry args={[radius * 8, radius * 8]} />
        <meshStandardMaterial color={COLORS.ground} roughness={1} />
      </mesh>

      <Floor />
      <Walls />
      <Items />

      <OrbitControls
        target={[cx, wallH * 0.35, cz]}
        enableDamping
        dampingFactor={0.08}
        minDistance={radius * 0.45}
        maxDistance={radius * 3.2}
        maxPolarAngle={Math.PI / 2 - 0.04}
        makeDefault
      />
    </Canvas>
  );
}
