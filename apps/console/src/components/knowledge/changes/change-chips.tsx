'use client';

import { Bot, PencilLine, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { dateOnly } from '@/lib/format';
import type { ChangeOrigin, KnowledgeChange, TrustState } from '@/lib/types/knowledge-changes';
import { cn } from '@/lib/utils';

/** Adapted from the shared component library's trust chips: same palette for verified / changed / unverified and conflict. */
export function TrustChip({ state, className }: { state: TrustState; className?: string }) {
  if (state === 'verified')
    return (
      <Badge variant="outline" className={cn('border-green-600/40 bg-green-500/10 text-green-700 dark:text-green-400', className)}>
        Verified
      </Badge>
    );
  if (state === 'changed')
    return (
      <Badge variant="outline" className={cn('border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400', className)}>
        Changed since verified
      </Badge>
    );
  return (
    <Badge variant="outline" className={cn('text-muted-foreground', className)}>
      Unverified
    </Badge>
  );
}

export function FreshnessChip({ change, className }: { change: Pick<KnowledgeChange, 'freshness' | 'reviewBy'>; className?: string }) {
  return change.freshness === 'stale' ? (
    <Badge variant="outline" className={cn('border-amber-600/40 bg-amber-500/10 text-amber-700 dark:text-amber-400', className)}>
      Review overdue since {dateOnly(change.reviewBy)}
    </Badge>
  ) : (
    <Badge variant="outline" className={cn('font-normal text-muted-foreground', className)}>
      Fresh · review by {dateOnly(change.reviewBy)}
    </Badge>
  );
}

export function ConflictChip({ resolved, className }: { resolved?: boolean; className?: string }) {
  return resolved ? (
    <Badge variant="outline" className={cn('font-normal text-muted-foreground', className)}>
      Conflict resolved
    </Badge>
  ) : (
    <Badge variant="outline" className={cn('border-red-600/40 bg-red-500/10 text-red-700 dark:text-red-400', className)}>
      Conflict
    </Badge>
  );
}

const ORIGIN: Record<ChangeOrigin, { label: string; icon: typeof Bot }> = {
  curation: { label: 'Curation', icon: PencilLine },
  agent_fix: { label: 'Agent fix', icon: Bot },
  source_sync: { label: 'Source sync', icon: RefreshCw },
};
export const ORIGIN_OPTIONS = (Object.keys(ORIGIN) as ChangeOrigin[]).map((value) => ({ value, label: ORIGIN[value].label }));

/** Who proposed the change, as the shared component library's `AuthorChip` shows agent / human / synced authors. */
export function OriginChip({ origin, className }: { origin: ChangeOrigin; className?: string }) {
  const O = ORIGIN[origin];
  return (
    <Badge variant="secondary" className={cn('gap-1 font-normal', className)}>
      <O.icon className="size-3" aria-hidden /> {O.label}
    </Badge>
  );
}
