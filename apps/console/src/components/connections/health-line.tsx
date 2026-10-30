import { CircleCheck, CircleX } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';

export interface HealthView {
  status: string;
  httpStatus?: number | null;
  code?: string | null;
  message?: string | null;
  latencyMs?: number | null;
  at: string;
  account?: string;
  environment?: string;
}

/**
 * One test's result as the connection page and the connect dialog both show it: Working or Failed, the system's status
 * or why there was no answer, how long it took, and when.
 */
export function HealthLine({ health, testId = 'health', who = true }: { health: HealthView; testId?: string; who?: boolean }) {
  const ok = health.status === 'ok';
  return (
    <div className="flex min-w-0 flex-col gap-1" data-testid={testId} data-status={health.status}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={cn(ok ? 'border-success/40 bg-success/10 text-success-text' : 'border-destructive/40 bg-destructive/10 text-destructive')}
        >
          {ok ? <CircleCheck /> : <CircleX />}
          {ok ? 'Working' : 'Failed'}
        </Badge>
        <span className="text-sm">
          {health.httpStatus ? `${health.httpStatus}` : (health.code ?? 'No answer')}
          {health.latencyMs != null && ` in ${health.latencyMs} ms`}
        </span>
      </div>
      {health.message && <p className="text-sm break-words text-muted-foreground">{health.message}</p>}
      <p className="text-xs text-muted-foreground">
        {relativeTime(health.at)}
        {who && health.account && `, ${health.account === 'team' ? 'with the team account' : 'with your own account'}`}
        {who && health.environment && `, ${health.environment}`}
      </p>
    </div>
  );
}
