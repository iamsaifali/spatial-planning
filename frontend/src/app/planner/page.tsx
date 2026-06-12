import type { Metadata } from "next";
import { PlannerShell } from "@/components/layout/PlannerShell";

export const metadata: Metadata = {
  title: "Planner - ZORY",
};

export default function PlannerPage() {
  return <PlannerShell />;
}
