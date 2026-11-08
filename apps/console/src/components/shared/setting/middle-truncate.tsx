import { middleShorten } from '@/lib/middle-shorten';
import { cn } from '@/lib/utils';

/** A long value kept readable at both ends ("ws_9f3a…c41d", "gr_no_…advice"), never cut mid-word; the whole value is in the title. */
export function MiddleTruncate({ text, head = 6, tail = 4, className }: { text: string; head?: number; tail?: number; className?: string }) {
  const short = middleShorten(text, head, tail);
  return (
    <span title={text} className={cn('font-mono', className)} data-full={text}>
      {short}
    </span>
  );
}
