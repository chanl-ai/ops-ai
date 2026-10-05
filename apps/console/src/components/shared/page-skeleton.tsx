import { Skeleton } from '@/components/ui/skeleton';
import { StatCardGrid } from '@/components/shared/stat-card';

interface PageSkeletonProps {
  /** Number of stat card skeletons to show (0 to hide stats section) */
  statCards?: number;
  /** Number of table row skeletons to show */
  tableRows?: number;
  /** Whether to show the toolbar skeleton (search + filters) */
  showToolbar?: boolean;
  /** Saved-view tabs above the toolbar (0 to hide) */
  viewTabs?: number;
}

export function PageSkeleton({
  statCards = 4,
  tableRows = 5,
  showToolbar = true,
  viewTabs = 0,
}: PageSkeletonProps) {
  return (
    <div className="space-y-6" data-testid="page-skeleton">
      {/* Stat cards skeleton */}
      {statCards > 0 && (
        <StatCardGrid>
          {Array.from({ length: statCards }).map((_, i) => (
            <div key={i} className="rounded-xl border bg-card p-6 space-y-3">
              <div className="flex items-center justify-between">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-4 rounded-full" />
              </div>
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-3 w-32" />
            </div>
          ))}
        </StatCardGrid>
      )}

      {viewTabs > 0 && (
        <div className="flex items-center gap-2">
          {Array.from({ length: viewTabs }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-32 rounded-md" />
          ))}
        </div>
      )}

      {/* Toolbar skeleton */}
      {showToolbar && (
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 flex-1">
            <Skeleton className="h-9 w-64" />
            <Skeleton className="h-9 w-24" />
          </div>
          <Skeleton className="h-9 w-9" />
        </div>
      )}

      {/* Table skeleton */}
      <div className="rounded-lg border">
        {/* Header */}
        <div className="flex items-center gap-4 border-b p-4">
          {[120, 80, 96, 64, 48].map((w, i) => (
            <Skeleton key={i} className="h-4" style={{ width: w }} />
          ))}
        </div>
        {/* Rows */}
        {Array.from({ length: tableRows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 border-b last:border-0 p-4">
            <Skeleton className="h-8 w-8 rounded-full" />
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}
