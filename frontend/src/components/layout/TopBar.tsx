"use client";

import { ArrowLeft, Pencil, Redo2, Undo2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useCurrencyStore } from "@/stores/currencyStore";
import { redo, undo, usePlannerStore } from "@/stores/plannerStore";

function DesignName() {
  const designName = usePlannerStore((s) => s.designName);
  const dirty = usePlannerStore((s) => s.dirtySinceSave);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(designName);

  const commit = () => {
    const name = draft.trim() || "My Living Room";
    usePlannerStore.setState({ designName: name, dirtySinceSave: true });
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        maxLength={120}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setEditing(false);
        }}
        aria-label="Design name"
        className="hidden h-8 w-48 rounded-md border border-line bg-surface px-2 text-sm font-medium sm:block"
      />
    );
  }
  return (
    <button
      onClick={() => {
        setDraft(designName);
        setEditing(true);
      }}
      title="Rename design"
      className="group hidden min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-sm font-medium text-ink-soft hover:bg-surface-2 hover:text-ink sm:flex"
    >
      <span className="truncate">{designName}</span>
      {dirty && <span className="text-ink-faint" title="Unsaved changes">•</span>}
      <Pencil className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-60" aria-hidden />
    </button>
  );
}

function CurrencyToggle() {
  const currency = useCurrencyStore((s) => s.currency);
  const supported = useCurrencyStore((s) => s.config.supported);
  const setCurrency = useCurrencyStore((s) => s.setCurrency);

  return (
    <div
      className="flex items-center rounded-full border border-line bg-surface p-0.5"
      role="group"
      aria-label="Display currency"
    >
      {supported.map((code) => (
        <button
          key={code}
          onClick={() => setCurrency(code)}
          aria-pressed={currency === code}
          className={`rounded-full px-2.5 py-1 text-[11px] font-bold transition-colors ${
            currency === code ? "bg-accent text-accent-ink" : "text-ink-soft hover:text-ink"
          }`}
        >
          {code}
        </button>
      ))}
    </div>
  );
}

export function TopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 sm:px-4">
      <Link
        href="/"
        className="flex items-center gap-2 rounded-full p-1.5 text-ink-soft hover:bg-surface-2 hover:text-ink"
        aria-label="Back to home"
      >
        <ArrowLeft className="h-4 w-4" />
      </Link>
      <span className="text-base font-black tracking-tight">ZORY</span>
      <span className="mx-1 hidden h-5 w-px bg-line sm:block" aria-hidden />
      <DesignName />

      <div className="ml-auto flex items-center gap-1.5">
        <div className="hidden items-center gap-0.5 sm:flex">
          <button
            onClick={undo}
            title="Undo (Cmd+Z)"
            aria-label="Undo"
            className="flex h-9 w-9 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2 hover:text-ink"
          >
            <Undo2 className="h-4 w-4" />
          </button>
          <button
            onClick={redo}
            title="Redo"
            aria-label="Redo"
            className="flex h-9 w-9 items-center justify-center rounded-full text-ink-soft hover:bg-surface-2 hover:text-ink"
          >
            <Redo2 className="h-4 w-4" />
          </button>
        </div>
        <CurrencyToggle />
      </div>
    </header>
  );
}
