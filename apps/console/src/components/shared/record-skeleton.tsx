import { Skeleton } from '@/components/ui/skeleton';

/** Loading shape of a RecordLayout page: header, 320px rail of cards, stat row and tabbed main. */
export function RecordSkeleton({ railSide = 'left' }: { railSide?: 'left' | 'right' }) {
  return (
    <div className="flex flex-col gap-4 px-6 py-6 lg:px-8" data-testid="record-skeleton">
      <div className="flex items-center gap-3">
        <Skeleton className="size-14 rounded-lg" />
        <div className="flex flex-col gap-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-80" />
        </div>
      </div>
      <div className={railSide === 'left' ? 'grid gap-4 lg:grid-cols-[320px_1fr]' : 'grid gap-4 lg:grid-cols-[1fr_300px] [&>:first-child]:lg:order-2'}>
        <div className="flex flex-col gap-4">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-32 rounded-xl" />
        </div>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      </div>
    </div>
  );
}
