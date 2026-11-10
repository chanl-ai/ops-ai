'use client';

import { Bot, MessageSquareQuote, PencilLine, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { dateOnly } from '@/lib/format';
import type { ChangeOrigin, ChangeStatus, KnowledgeChange, TrustState } from '@/lib/types/knowledge-changes';
import { cn } from '@/lib/utils';

/** Adapted from the shared component library's trust chips: same palette for verified / changed / unverified and conflict. */
export function TrustChip({ state, className }: { state: TrustState; className?: string }) {
  if (state === 'verified')
    return (
      <Badge variant="outline" className={cn('border-success/40 bg-success/10 text-success-text', className)}>
        Verified
      </Badge>
    );
  if (state === 'changed')
    return (
      <Badge variant="outline" className={cn('border-warning/40 bg-warning/10 text-warning-text', className)}>
        Changed since verified
      </Badge>
    );
  if (state === 'source_changed')
    return (
      <Badge variant="outline" className={cn('border-destructive/40 bg-destructive/10 text-destructive-text', className)}>
        Source changed
      </Badge>
    );
  return (
    <Badge variant="outline" className={cn('text-muted-foreground', className)}>
      {state === 'draft' ? 'Draft' : 'Unverified'}
    </Badge>
  );
}

export function FreshnessChip({ change, className }: { change: Pick<KnowledgeChange, 'freshness' | 'reviewBy'>; className?: string }) {
  return change.freshness === 'stale' ? (
    <Badge variant="outline" className={cn('border-warning/40 bg-warning/10 text-warning-text', className)}>
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
    <Badge variant="outline" className={cn('border-destructive/40 bg-destructive/10 text-destructive-text', className)}>
      Conflict
    </Badge>
  );
}

const STATUS_WORD: Record<ChangeStatus, string> = { pending: 'Waiting', approved: 'Approved', rejected: 'Rejected', applied: 'Applied', superseded: 'Superseded', source_changed: 'Source changed' };
export const statusWord = (s: ChangeStatus) => STATUS_WORD[s] ?? s;

/**
 * The check on an FAQ draft, from the draft itself: the source changed since it was drafted, or its answer uses words its
 * passage lacks, or nothing found.
 */
export function FaqCheck({ change, className }: { change: Pick<KnowledgeChange, 'status' | 'faq'>; className?: string }) {
  if (change.status === 'source_changed')
    return (
      <Badge variant="outline" className={cn('border-destructive/40 bg-destructive/10 text-destructive-text', className)}>
        Source changed
      </Badge>
    );
  const adds = change.faq?.addsWords ?? [];
  if (adds.length)
    return (
      <Badge variant="outline" className={cn('max-w-56 border-warning/40 bg-warning/10 whitespace-normal text-warning-text', className)}>
        Answer adds {adds.map((w) => `“${w}”`).join(', ')}; the passage does not say {adds.length === 1 ? 'it' : 'them'}
      </Badge>
    );
  return <span className={cn('text-xs text-muted-foreground', className)}>No issues found</span>;
}

const ORIGIN: Record<ChangeOrigin, { label: string; icon: typeof Bot }> = {
  curation: { label: 'Curation', icon: PencilLine },
  agent_fix: { label: 'Agent fix', icon: Bot },
  source_sync: { label: 'Source sync', icon: RefreshCw },
  generated_faq: { label: 'Generated FAQ', icon: MessageSquareQuote },
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
