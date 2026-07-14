"use client";

import { RotateCw, Trash2 } from "lucide-react";
import { removeItem, validateItemDebounced } from "@/lib/placement";
import { categoryName } from "@/lib/constants";
import { usePlannerStore } from "@/stores/plannerStore";
import { useProductStore } from "@/stores/productStore";
import { useUiStore } from "@/stores/uiStore";

/** Floating actions for the selected item: rotate / delete.
 *  Doubles as the touch path for actions that otherwise need a keyboard. */
export function ItemActionsBar() {
  const selectedId = useUiStore((s) => s.selectedId);
  const items = usePlannerStore((s) => s.items);
  const byId = useProductStore((s) => s.byId);

  const item = items.find((i) => i.instance_id === selectedId);
  if (!item) return null;
  const product = byId[item.product_id];
  const name = item.custom?.name ?? product?.name ?? "Item";

  const rotate = () => {
    usePlannerStore.getState().moveItem(item.instance_id, {
      rotation_deg: (item.rotation_deg + 90) % 360,
    });
    validateItemDebounced(item.instance_id);
  };

  return (
    <div className="pointer-events-auto flex max-w-[calc(100vw-16px)] items-center gap-1 overflow-x-auto rounded-full border border-line bg-surface px-2 py-1.5 shadow-pop">
      <span className="max-w-36 truncate px-1.5 text-xs font-semibold" title={name}>
        {product ? categoryName(product.category) : name}
      </span>
      <span className="h-4 w-px shrink-0 bg-line" aria-hidden />
      <ActionButton label="Rotate 90°" onClick={rotate}>
        <RotateCw className="h-3.5 w-3.5" />
      </ActionButton>
      <ActionButton label="Delete" onClick={() => removeItem(item.instance_id)} danger>
        <Trash2 className="h-3.5 w-3.5" />
      </ActionButton>
    </div>
  );
}

function ActionButton({
  label,
  onClick,
  children,
  danger = false,
  busy = false,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  danger?: boolean;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      disabled={busy}
      className={`flex h-8 shrink-0 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium disabled:opacity-50 ${
        danger ? "text-danger hover:bg-danger-soft" : "text-ink-soft hover:bg-surface-2 hover:text-ink"
      }`}
    >
      {children}
      <span className="hidden md:inline">{label}</span>
    </button>
  );
}
