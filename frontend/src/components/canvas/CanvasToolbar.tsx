"use client";

import {
  DoorOpen,
  Eye,
  EyeOff,
  LayoutTemplate,
  MousePointer2,
  PackagePlus,
  PenLine,
  RectangleHorizontal,
  Redo2,
  Ruler,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { DOOR_WIDTH_PRESETS, WINDOW_WIDTH_PRESETS } from "@/lib/constants";
import { redo, undo } from "@/stores/plannerStore";
import { useGuideStore } from "@/stores/guideStore";
import { useUiStore, type Tool } from "@/stores/uiStore";
import { CustomItemDialog } from "./CustomItemDialog";
import { RoomTemplatesDialog } from "./RoomTemplatesDialog";

const TOOLS: { key: Tool; icon: typeof MousePointer2; label: string; shortcut: string }[] = [
  { key: "select", icon: MousePointer2, label: "Select", shortcut: "V" },
  { key: "wall", icon: PenLine, label: "Draw Wall", shortcut: "W" },
  { key: "door", icon: DoorOpen, label: "Add Door", shortcut: "D" },
  { key: "window", icon: RectangleHorizontal, label: "Add Window", shortcut: "N" },
  { key: "measure", icon: Ruler, label: "Measure", shortcut: "M" },
];

function ToolbarButton({
  icon: Icon,
  label,
  active = false,
  onClick,
  title,
}: {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title ?? label}
      aria-label={label}
      aria-pressed={active}
      className={`flex h-10 w-10 shrink-0 flex-col items-center justify-center gap-0.5 rounded-2xl transition-colors md:h-11 md:w-auto md:min-w-14 md:px-2 ${
        active ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-surface-2 hover:text-ink"
      }`}
    >
      <Icon className="h-4 w-4" />
      {/* mockup parity: tool labels on desktop, icon-only on phones */}
      <span className="hidden text-[9px] font-semibold leading-3 whitespace-nowrap md:block">{label}</span>
    </button>
  );
}

export function CanvasToolbar() {
  const tool = useUiStore((s) => s.tool);
  const setTool = useUiStore((s) => s.setTool);
  const doorWidth = useUiStore((s) => s.doorWidth);
  const windowWidth = useUiStore((s) => s.windowWidth);
  const setOpeningWidth = useUiStore((s) => s.setOpeningWidth);
  const overlaysVisible = useGuideStore((s) => s.overlaysVisible);
  const toggleOverlays = useGuideStore((s) => s.toggleOverlays);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);

  const showWidths = tool === "door" || tool === "window";
  const presets = tool === "door" ? DOOR_WIDTH_PRESETS : WINDOW_WIDTH_PRESETS;
  const current = tool === "door" ? doorWidth : windowWidth;

  return (
    <>
      <div className="pointer-events-auto flex flex-col items-center gap-2">
        {showWidths && (
          <div className="flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-1 shadow-soft">
            <span className="px-1.5 text-[11px] font-medium text-ink-soft">Width</span>
            {presets.map((w) => (
              <button
                key={w}
                onClick={() => setOpeningWidth(tool as "door" | "window", w)}
                className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                  current === w ? "bg-accent text-accent-ink" : "text-ink-soft hover:bg-surface-2"
                }`}
              >
                {w}
              </button>
            ))}
            <span className="pr-1 text-[11px] text-ink-faint">cm</span>
          </div>
        )}

        <div className="panel-scroll flex max-w-[calc(100vw-16px)] items-center gap-0.5 overflow-x-auto rounded-3xl border border-line bg-surface p-1 shadow-soft">
          {TOOLS.map(({ key, icon, label, shortcut }) => (
            <ToolbarButton
              key={key}
              icon={icon}
              label={label}
              title={`${label} (${shortcut})`}
              active={tool === key}
              onClick={() => setTool(key)}
            />
          ))}
          <span className="mx-1 h-5 w-px shrink-0 bg-line" aria-hidden />
          <ToolbarButton
            icon={PackagePlus}
            label="Your Item"
            title="Add an item you already own"
            onClick={() => setCustomOpen(true)}
          />
          <ToolbarButton icon={LayoutTemplate} label="Templates" onClick={() => setTemplatesOpen(true)} />
          <ToolbarButton
            icon={overlaysVisible ? Eye : EyeOff}
            label="Analysis"
            title={overlaysVisible ? "Hide analysis overlays" : "Show walkways & keep-clear zones"}
            active={overlaysVisible}
            onClick={toggleOverlays}
          />
          <span className="mx-1 h-5 w-px shrink-0 bg-line" aria-hidden />
          <ToolbarButton icon={Undo2} label="Undo" title="Undo (Cmd+Z)" onClick={undo} />
          <ToolbarButton icon={Redo2} label="Redo" title="Redo (Cmd+Shift+Z)" onClick={redo} />
        </div>

        {tool === "wall" && (
          <p className="rounded-full bg-accent/85 px-3 py-1 text-[11px] font-medium text-accent-ink">
            Click to place corners · click the first corner or press Enter to close · Esc cancels
          </p>
        )}
        {showWidths && (
          <p className="rounded-full bg-accent/85 px-3 py-1 text-[11px] font-medium text-accent-ink">
            Move along a wall and click to place
          </p>
        )}
      </div>
      <RoomTemplatesDialog open={templatesOpen} onClose={() => setTemplatesOpen(false)} />
      <CustomItemDialog open={customOpen} onClose={() => setCustomOpen(false)} />
    </>
  );
}
