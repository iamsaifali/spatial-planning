"use client";

import { PackagePlus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { addCustomItemToRoom } from "@/lib/placement";
import { useUiStore } from "@/stores/uiStore";

/** "Existing items you want to keep" (requirements 5, step 2). */
export function CustomItemDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useUiStore((s) => s.toast);
  const [name, setName] = useState("");
  const [w, setW] = useState(120);
  const [d, setD] = useState(45);
  const [h, setH] = useState(75);

  const valid = name.trim().length > 0 && w >= 10 && w <= 1000 && d >= 10 && d <= 1000 && h >= 1 && h <= 400;

  const add = () => {
    if (!valid) return;
    addCustomItemToRoom({ name: name.trim(), width_cm: w, depth_cm: d, height_cm: h });
    toast("success", `${name.trim()} placed - drag it to where it lives.`);
    setName("");
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add an item you already own"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={add} disabled={!valid}>
            <PackagePlus className="h-4 w-4" />
            Place item
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-xs leading-5 text-ink-soft">
          ZORY plans around items you&apos;re keeping - they take up space on the canvas and in the
          spatial checks, but aren&apos;t shoppable.
        </p>
        <label className="block text-xs font-medium text-ink-soft">
          What is it?
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
            placeholder="e.g. Grandma's teak cabinet"
            className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2.5 text-sm"
          />
        </label>
        <div className="flex flex-wrap gap-3">
          {(
            [
              ["Width", w, setW, 1000],
              ["Depth", d, setD, 1000],
              ["Height", h, setH, 400],
            ] as const
          ).map(([label, value, setter, max]) => (
            <label key={label} className="text-xs font-medium text-ink-soft">
              {label} (cm)
              <input
                type="number"
                min={10}
                max={max}
                value={value}
                onChange={(e) => setter(Number(e.target.value))}
                className="mt-1 block w-24 rounded-md border border-line bg-surface px-3 py-2 text-sm"
              />
            </label>
          ))}
        </div>
      </div>
    </Dialog>
  );
}
