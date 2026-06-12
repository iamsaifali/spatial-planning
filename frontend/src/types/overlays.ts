import type { Pose } from "@/types/api";

export type { AnalysisResponse, Point, Zone } from "@/types/api";

export interface GhostPreviewPose {
  productId: string;
  pose: Pose;
  label: string;
}
