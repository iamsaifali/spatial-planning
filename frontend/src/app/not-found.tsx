import { Compass } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-bg p-6 text-center">
      <Compass className="h-10 w-10 text-ink-faint" />
      <h1 className="text-2xl font-black tracking-tight">Page not found</h1>
      <p className="max-w-xs text-sm leading-6 text-ink-soft">
        The page you&apos;re looking for doesn&apos;t exist. Your room plan is safe.
      </p>
      <Link
        href="/planner"
        className="rounded-full bg-accent px-6 py-3 text-sm font-semibold text-accent-ink hover:bg-ink-soft"
      >
        Back to the planner
      </Link>
    </div>
  );
}
