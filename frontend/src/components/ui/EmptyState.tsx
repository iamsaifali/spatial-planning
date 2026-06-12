import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon: LucideIcon;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong bg-surface-2/60 px-6 py-8 text-center">
      <Icon className="h-7 w-7 text-ink-faint" aria-hidden />
      <p className="text-sm font-semibold text-ink">{title}</p>
      {body && <p className="max-w-xs text-xs leading-5 text-ink-soft">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
