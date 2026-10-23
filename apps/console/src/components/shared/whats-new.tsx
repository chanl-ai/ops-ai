'use client';

import * as React from 'react';

import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useChangelog } from '@/hooks/use-changelog';
import type { ChangelogEntry } from '@/lib/changelog';
import { dateOnly } from '@/lib/format';
import { cn } from '@/lib/utils';

const TAG: Record<ChangelogEntry['tag'], { label: string; variant: 'default' | 'secondary' | 'outline' }> = {
  new: { label: 'New', variant: 'default' },
  improved: { label: 'Improved', variant: 'secondary' },
  fix: { label: 'Fix', variant: 'outline' },
};

/** chanl-eval's What's new mark: a ring with an arc inside, turned a quarter. */
function WhatsNewMark() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="size-7" aria-hidden>
      <g transform="rotate(-90 12 12)">
        <path d="M5.636 5.636a9 9 0 1 0 12.728 12.728a9 9 0 0 0 -12.728 -12.728z" />
        <path d="M16.243 7.757a6 6 0 0 0 -8.486 0" />
      </g>
    </svg>
  );
}

/**
 * What's new (c-510): chanl-eval's floating What's New button, bottom-right on every console page, its popover opening
 * upward with a Coming next tab for the roadmap and the build's version in its header. A dot marks an entry this
 * person has not opened, and a ring pulses now and then while it is closed; opening the popover clears the dot.
 */
export function WhatsNew() {
  const { entries, roadmap, unseen, markSeen, version, feedbackOn } = useChangelog();
  const [open, setOpen] = React.useState(false);
  const [pulsing, setPulsing] = React.useState(false);
  // chanl-eval's attention pulse: once after three seconds, then every eighteen, never while the popover is open.
  React.useEffect(() => {
    if (open) return;
    const pulse = () => {
      setPulsing(true);
      window.setTimeout(() => setPulsing(false), 2000);
    };
    const first = window.setTimeout(pulse, 3000);
    const every = window.setInterval(pulse, 18000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(every);
    };
  }, [open]);
  return (
    // Above the dev Feedback button (16px from the corner) when it shares the corner, so neither covers the other.
    <div className={cn('fixed right-4 z-50', feedbackOn ? 'bottom-16' : 'bottom-4')}>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) markSeen();
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            className="relative flex size-12 items-center justify-center rounded-full bg-foreground text-background shadow-lg transition-transform select-none hover:scale-105 active:scale-95"
            aria-label="What’s new"
            data-testid="whats-new-trigger"
          >
            {pulsing && <span className="absolute inset-0 animate-ping rounded-full border-2 border-primary/40" aria-hidden />}
            <WhatsNewMark />
            {unseen && <span className="absolute top-0 right-0 size-3 rounded-full bg-primary ring-2 ring-background" data-testid="whats-new-dot" aria-label="New changes" />}
          </button>
        </PopoverTrigger>
        <PopoverContent side="top" align="end" sideOffset={12} className="w-80 max-w-[calc(100vw-2rem)] p-0" data-testid="whats-new-popup">
          <Tabs defaultValue="new" className="gap-0">
            <div className="flex items-center justify-between gap-2 p-3">
              <TabsList>
                <TabsTrigger value="new">What’s new</TabsTrigger>
                <TabsTrigger value="next">Coming next</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="new" className="border-t">
              <ScrollArea className="h-80">
                <ol className="flex flex-col gap-4 p-4">
                  {entries.length === 0 ? (
                    <li className="py-4 text-center text-xs text-muted-foreground">Nothing new yet.</li>
                  ) : (
                    entries.map((e) => (
                      <li key={e.id} className="flex flex-col gap-1.5" data-testid="whats-new-entry">
                        <div className="flex items-center gap-2">
                          <Badge variant={TAG[e.tag].variant}>{TAG[e.tag].label}</Badge>
                          <span className="text-xs text-muted-foreground tabular-nums">{dateOnly(e.date)}</span>
                        </div>
                        <p className="text-sm font-medium leading-tight">{e.title}</p>
                        {e.description && <p className="text-xs leading-relaxed text-muted-foreground">{e.description}</p>}
                      </li>
                    ))
                  )}
                </ol>
              </ScrollArea>
            </TabsContent>
            <TabsContent value="next" className="border-t">
              <ScrollArea className="h-80">
                <ol className="flex flex-col gap-4 p-4" data-testid="coming-next">
                  {roadmap.length === 0 ? (
                    <li className="py-4 text-center text-xs text-muted-foreground">The roadmap is being written.</li>
                  ) : (
                    roadmap.map((r) => (
                      <li key={r.title} className="flex flex-col gap-1">
                        <p className="text-sm font-medium leading-tight">{r.title}</p>
                        <p className="text-xs leading-relaxed text-muted-foreground">{r.line}</p>
                      </li>
                    ))
                  )}
                </ol>
              </ScrollArea>
            </TabsContent>
          </Tabs>
          {version && (
            <p className="truncate border-t px-4 py-2 text-xs text-muted-foreground tabular-nums" title="The version this console was built from" data-testid="whats-new-version">
              Version {version}
            </p>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
