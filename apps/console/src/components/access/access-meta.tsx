import { AlertTriangle, CircleSlash } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { relativeTime, shortDate } from '@/lib/format';
import type { Capability, GrantScope, GrantStatus } from '@/lib/types/governance';
import { cn } from '@/lib/utils';

export const SCOPE_LABEL: Record<GrantScope, string> = { read: 'Read', write: 'Write', money_movement: 'Moves money' };
export const GRANT_STATUS_LABEL: Record<GrantStatus, string> = { active: 'Active', expiring: 'Expiring soon', expired: 'Expired' };
export const CAPABILITY_LABEL: Record<Capability, string> = { author: 'Author', approve: 'Approve', publish: 'Publish' };
export const RESOURCE_KIND_LABEL = { module: 'System module', knowledge_base: 'Knowledge base' } as const;

export function ScopeBadge({ scope }: { scope: GrantScope }) {
  const tone = scope === 'money_movement' ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300' : scope === 'write' ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300' : '';
  return (
    <Badge variant="outline" className={cn('font-normal', tone)}>
      {SCOPE_LABEL[scope]}
    </Badge>
  );
}

/** Expiry with its urgency: never, a date, or how soon / how long ago. */
export function ExpiryText({ expiresAt, status }: { expiresAt: string; status: GrantStatus }) {
  const days = Math.round((new Date(expiresAt).getTime() - Date.now()) / 86_400_000);
  if (status === 'expired')
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium whitespace-nowrap text-red-600 dark:text-red-400">
        <CircleSlash className="size-3.5" /> Expired {relativeTime(expiresAt)}
      </span>
    );
  if (status === 'expiring')
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium whitespace-nowrap text-amber-700 dark:text-amber-400">
        <AlertTriangle className="size-3.5" /> In {days === 1 ? '1 day' : `${days} days`}
      </span>
    );
  return <span className="text-xs whitespace-nowrap text-muted-foreground">{shortDate(expiresAt)}</span>;
}

export function CapabilityChips({ capabilities }: { capabilities: Capability[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {(['author', 'approve', 'publish'] as const).map((c) => (
        <Badge key={c} variant={capabilities.includes(c) ? 'secondary' : 'outline'} className={cn('font-normal', !capabilities.includes(c) && 'text-muted-foreground/50 line-through')}>
          {CAPABILITY_LABEL[c]}
        </Badge>
      ))}
    </div>
  );
}
