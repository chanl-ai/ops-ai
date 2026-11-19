'use client';

import * as React from 'react';
import type { LucideIcon } from 'lucide-react';

import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';

import type { MenuPick } from './extensions';

export interface MenuRow {
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
  pick: MenuPick;
}

export interface MenuSection {
  label: string;
  rows: MenuRow[];
}

/**
 * The menu a typed `@`, `{{` or `/` opens, under the caret. The caret stays in the document: the document forwards
 * the arrow keys and Enter, and this draws the highlighted row. What was typed after the trigger is the search, so
 * there is no search box of its own.
 */
export function CaretMenu({
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
}: {
  /** Where the trigger sits on screen. */
  rect: () => DOMRect | null;
  label: string;
  status: 'loading' | 'ready' | 'error';
  sections: MenuSection[];
  active: string;
  onActive: (key: string) => void;
  onPick: (row: MenuRow) => void;
  onDismiss: () => void;
  empty: string;
  error: string;
  /** The menu's element id, so the document can point a screen reader at its list and highlighted row. */
  id: string;
}) {
  const anchor = React.useRef({ getBoundingClientRect: () => rect() ?? new DOMRect() });
  anchor.current.getBoundingClientRect = () => rect() ?? new DOMRect();
  const note = sections.flatMap((s) => s.rows).find((r) => r.key === active)?.note;
  return (
    <Popover open onOpenChange={(open) => !open && onDismiss()}>
      <PopoverAnchor virtualRef={anchor} />
      <PopoverContent
        align="start"
        side="bottom"
        className="w-96 max-w-[calc(100vw-2rem)] p-0"
        // The caret stays in the document while the menu is open.
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onFocusOutside={(e) => e.preventDefault()}
        onMouseDown={(e) => e.preventDefault()}
        id={id}
        data-testid="caret-menu"
      >
        <Command shouldFilter={false} value={active} onValueChange={onActive}>
          <CommandList label={label} className="max-h-72">
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
              </>
            )}
          </CommandList>
        </Command>
        {note && status === 'ready' && <div className="border-t px-3 py-1.5 text-xs text-muted-foreground">{note}</div>}
      </PopoverContent>
    </Popover>
  );
}
