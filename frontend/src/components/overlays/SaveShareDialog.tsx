"use client";

import { Check, Copy, Link2, Save } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { api, ApiError } from "@/lib/api";
import { usePlannerStore } from "@/stores/plannerStore";
import { usePrefsStore } from "@/stores/prefsStore";
import { useUiStore } from "@/stores/uiStore";

export function SaveShareDialog() {
  const open = useUiStore((s) => s.shareOpen);
  const setSheet = useUiStore((s) => s.setSheet);
  const designName = usePlannerStore((s) => s.designName);
  const markSaved = usePlannerStore((s) => s.markSaved);

  const [name, setName] = useState(designName);
  const [busy, setBusy] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setSheet("shareOpen", false);
    setShareUrl(null);
    setCopied(false);
    setError(null);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const { room, items } = usePlannerStore.getState();
      const prefs = usePrefsStore.getState().preferences;
      const res = await api.saveDesign(name.trim() || "My Living Room", room, items, prefs);
      markSaved(res.design_id);
      usePlannerStore.setState({ designName: name.trim() || "My Living Room" });
      setShareUrl(`${window.location.origin}/planner/${res.design_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save - is the backend running?");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard may be unavailable; the URL is selectable below
    }
  };

  return (
    <Dialog open={open} onClose={close} title="Save & share design">
      <div className="space-y-4">
        <label className="block text-xs font-medium text-ink-soft">
          Design name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2.5 text-sm"
            placeholder="My Living Room"
          />
        </label>

        {error && <p className="rounded-md bg-danger-soft p-2.5 text-xs text-danger">{error}</p>}

        {shareUrl ? (
          <div className="space-y-2 rounded-lg border border-success/25 bg-success-soft p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-success">
              <Check className="h-4 w-4" /> Saved! Anyone with this link can open the design:
            </p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-md bg-surface px-2.5 py-2 text-[11px]">{shareUrl}</code>
              <Button size="sm" variant="secondary" onClick={() => void copy()}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>
        ) : (
          <Button onClick={() => void save()} loading={busy} className="w-full" size="lg">
            {!busy && <Save className="h-4 w-4" />}
            Save design
          </Button>
        )}

        <p className="flex items-start gap-1.5 text-[11px] leading-4 text-ink-faint">
          <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Saving creates a snapshot link. Save again after more edits to get an updated link.
        </p>
      </div>
    </Dialog>
  );
}
