import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';

/** Spend or volume against a limit. Turns to a warning at 80% and to an error at the limit. */
export function UsageBar({ label, used, limit, format = (n) => n.toLocaleString('en-CA') }: { label: string; used: number; limit: number; format?: (n: number) => string }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const tone = pct >= 100 ? 'error' : pct >= 80 ? 'warn' : 'ok';
  return (
    <div className="flex flex-col gap-1.5" data-testid="usage-bar" data-tone={tone}>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {format(used)} of {format(limit)} · {Math.round(pct)}%
        </span>
      </div>
      <Progress value={pct} aria-label={label} className={cn(tone === 'ok' && 'bg-primary/15', tone === 'warn' && 'bg-warning/20 *:bg-warning-text', tone === 'error' && 'bg-destructive/20 *:bg-destructive')} />
    </div>
  );
}
