import { Badge } from '@/components/ui/badge';
import type { Citation } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

/** The flags a citation carries wherever it shows: in force on an as-of date, stale, or from a revoked connection. */
export function CitationFlags({ citation: c, className }: { citation: Citation; className?: string }) {
  if (!c.inForceOn && !c.stale && !c.connectionRevoked) return null;
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)} data-testid="citation-flags">
      {c.inForceOn && (
        <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal whitespace-nowrap">
          In force on {c.inForceOn}
        </Badge>
      )}
      {c.inForceOn && c.supersededToday && <span className="text-[10px] text-muted-foreground">superseded since</span>}
      {c.stale && (
        <Badge variant="outline" className="h-4 border-amber-300 px-1 text-[10px] font-normal text-amber-700 dark:border-amber-800 dark:text-amber-400">
          Stale
        </Badge>
      )}
      {c.connectionRevoked && (
        <Badge variant="outline" className="h-4 border-destructive/40 px-1 text-[10px] font-normal whitespace-nowrap text-destructive">
          Connection revoked
        </Badge>
      )}
    </span>
  );
}
