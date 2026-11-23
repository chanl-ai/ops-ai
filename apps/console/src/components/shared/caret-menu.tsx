'use client';

import * as React from 'react';
import { Loader2, type LucideIcon } from 'lucide-react';

import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';

/** One row; `P` is what picking it does, which only the caller reads. */
export interface MenuRow<P = unknown> {
  /** Unique in the menu; the highlighted row is tracked by it. */
  key: string;
  label: string;
  icon?: LucideIcon;
  /** The muted text on the right: what the row is, or what picking it does. */
  trailing?: string | null;
  /** Why the row cannot be picked. */
  disabled?: string | null;
  /** Shown under the list while the row is highlighted. */
  note?: string | null;
  pick: P;
}

export interface MenuSection<P = unknown> {
  label: string;
  rows: MenuRow<P>[];
}

/**
 * The one list opened at the caret: a typed `@`, `{{`, `/` or `if `. The caret stays in the text: the text forwards the
 * arrow keys and Enter, and this draws the highlighted row. What was typed after the trigger is the search, which the
 * caller runs on the server (hooks/options-queries.ts), so there is no search box and nothing is filtered here.
 *
 * The list is capped at 18rem and scrolls under sticky group headings, so a long list never runs off the screen and
 * every group stays reachable; the highlighted row is kept in view as the arrow keys move it. `onEnd` asks for the
 * next page when the list is scrolled, or arrowed, to its end.
 */
export function CaretMenu<P>({
  rect,
  label,
  status,
  sections,
  active,
  onActive,
  onPick,
  onDismiss,
  empty,
  error,
  id,
  onEnd,
  loadingMore = false,
}: {
  /** Where the trigger sits on screen. */
  rect: () => DOMRect | null;
  label: string;
  status: 'loading' | 'ready' | 'error';
  sections: MenuSection<P>[];
  active: string;
  onActive: (key: string) => void;
  onPick: (row: MenuRow<P>) => void;
  onDismiss: () => void;
  empty: string;
  error: string;
  /** The menu's element id, so the text can point a screen reader at its list and highlighted row. */
  id: string;
  onEnd?: () => void;
  loadingMore?: boolean;
}) {
  const anchor = React.useRef({ getBoundingClientRect: () => rect() ?? new DOMRect() });
  anchor.current.getBoundingClientRect = () => rect() ?? new DOMRect();
  const list = React.useRef<HTMLDivElement>(null);
  const rows = sections.flatMap((s) => s.rows);
  const note = rows.find((r) => r.key === active)?.note;
  const last = rows.at(-1)?.key;
  React.useEffect(() => {
    // cmdk scrolls only for keys it handles itself; here the text handles them.
    list.current?.querySelector('[cmdk-item][data-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    if (active && active === last) onEnd?.();
  }, [active, last, onEnd]);
  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 48) onEnd?.();
  };
  return (
    <Popover open onOpenChange={(open) => !open && onDismiss()}>
      <PopoverAnchor virtualRef={anchor} />
      <PopoverContent
        align="start"
        side="bottom"
        collisionPadding={16}
        className="w-96 max-w-[calc(100vw-2rem)] p-0"
        // The caret stays in the text while the menu is open.
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onFocusOutside={(e) => e.preventDefault()}
        onMouseDown={(e) => e.preventDefault()}
        id={id}
        data-testid="caret-menu"
      >
        <Command shouldFilter={false} value={active} onValueChange={onActive}>
          <CommandList ref={list} label={label} onScroll={onScroll} className="max-h-[min(18rem,50vh)] [&_[cmdk-group-heading]]:sticky [&_[cmdk-group-heading]]:top-0 [&_[cmdk-group-heading]]:z-10 [&_[cmdk-group-heading]]:bg-popover">
            {status === 'loading' ? (
              <div className="space-y-2 p-3" role="status" aria-label="Searching">
                <Skeleton className="h-7" />
                <Skeleton className="h-7" />
                <Skeleton className="h-7" />
              </div>
            ) : status === 'error' ? (
              <p className="px-3 py-4 text-sm text-muted-foreground" role="alert">
                {error}
              </p>
            ) : (
              <>
                <CommandEmpty className="px-3 py-4 text-sm text-muted-foreground">{empty}</CommandEmpty>
                {sections.map((s) => (
                  <CommandGroup key={s.label} heading={s.label}>
                    {s.rows.map((r) => (
                      <CommandItem key={r.key} value={r.key} disabled={!!r.disabled} onSelect={() => onPick(r)}>
                        {r.icon && <r.icon />}
                        <span className="min-w-0 flex-1 truncate">{r.label}</span>
                        {(r.disabled ?? r.trailing) && <span className="max-w-[55%] shrink-0 truncate text-xs text-muted-foreground">{r.disabled ?? r.trailing}</span>}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ))}
                {loadingMore && (
                  <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground" role="status">
                    <Loader2 className="size-3 animate-spin" /> Loading more…
                  </div>
                )}
              </>
            )}
          </CommandList>
        </Command>
        {note && status === 'ready' && <div className="border-t px-3 py-1.5 text-xs text-muted-foreground">{note}</div>}
      </PopoverContent>
    </Popover>
  );
}
