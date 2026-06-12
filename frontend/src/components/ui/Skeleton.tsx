export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-beige-100/70 ${className}`} aria-hidden />;
}

export function RecommendationSkeleton() {
  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-3">
      <Skeleton className="h-36 w-full" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
      <Skeleton className="h-9 w-full rounded-full" />
    </div>
  );
}
