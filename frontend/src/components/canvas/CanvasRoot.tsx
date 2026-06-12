"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/Skeleton";

/** Konva touches `window`, so the stage loads client-side only. */
export const CanvasRoot = dynamic(() => import("./CanvasStage"), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 flex items-center justify-center">
      <Skeleton className="h-2/3 w-3/4 max-w-3xl" />
    </div>
  ),
});
