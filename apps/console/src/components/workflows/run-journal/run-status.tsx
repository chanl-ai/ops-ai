import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

const TONE: Record<string, string> = {
  succeeded: 'border-success/40 bg-success/10 text-success-text',
  ok: 'border-success/40 bg-success/10 text-success-text',
  failed: 'border-destructive/40 bg-destructive/10 text-destructive',
  error: 'border-destructive/40 bg-destructive/10 text-destructive',
  waiting: 'border-warning/40 bg-warning/10 text-warning-text',
  cancelled: 'border-border bg-muted text-muted-foreground',
};

/** A run's or a step's status as the runner reports it; unknown statuses show as they come. */
export function RunStatus({ status, testId }: { status: string; testId?: string }) {
  return (
    <Badge variant="outline" className={cn('font-normal capitalize', TONE[status])} data-testid={testId}>
      {status.replace(/_/g, ' ')}
    </Badge>
  );
}
