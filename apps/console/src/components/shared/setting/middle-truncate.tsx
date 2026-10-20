import { cn } from '@/lib/utils';

/** A long value kept readable at both ends ("ws_9f3a…c41d"); the whole value is in the title and the DOM text stays whole for copying. */
export function MiddleTruncate({ text, head = 6, tail = 4, className }: { text: string; head?: number; tail?: number; className?: string }) {
  const short = text.length > head + tail + 1 ? `${text.slice(0, head)}…${text.slice(-tail)}` : text;
  return (
    <span title={text} className={cn('font-mono', className)} data-full={text}>
      {short}
    </span>
  );
}
