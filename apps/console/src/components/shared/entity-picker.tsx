'use client';

import * as React from 'react';
import { Check, Loader2, Plus, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { type OptionSource, useOptionLabels, useOptionSearch } from '@/hooks/options-queries';
import { cn } from '@/lib/utils';

/**
 * Pick one or many entities from an `/options` route (c-135): the search runs on the server, the list pages in as it
 * scrolls, and chosen values show as chips labelled by id from the service. Every picker of agents, tools, knowledge
 * bases and the like uses this rather than filtering a list the browser loaded, which caps what can be found.
 */
export function EntityPicker({
  source,
  value,
  onChange,
  multiple = true,
  addLabel,
  searchPlaceholder = 'Search…',
  emptyText = 'Nothing matches.',
  icon: Icon,
  disabled,
  testId,
  open: openProp,
  onOpenChange,
  showChosen = true,
}: {
  source: OptionSource;
  value: string[];
  onChange: (next: string[]) => void;
  multiple?: boolean;
  addLabel: string;
  searchPlaceholder?: string;
  emptyText?: string;
  icon?: React.ComponentType<{ className?: string }>;
  disabled?: boolean;
  testId?: string;
  /** Controlled open state, for a page that opens the picker from elsewhere (the skills toolbar's always-on). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Off when the caller lists the chosen items itself (a file field's one list of attached files). */
  showChosen?: boolean;
}) {
  const [openState, setOpenState] = React.useState(false);
  const open = openProp ?? openState;
  const setOpen = (o: boolean) => (onOpenChange ? onOpenChange(o) : setOpenState(o));
  const [search, setSearch] = React.useState('');
  const results = useOptionSearch(source, search, open);
  const labels = useOptionLabels(source, value);
  const known = new Map((labels.data?.data ?? []).map((o) => [o.id, o]));
  const options = (results.data?.pages ?? []).flatMap((p) => p.data);
  const chosen = new Set(value);

  const pick = (id: string) => {
    if (!multiple) {
      onChange([id]);
      setOpen(false);
      return;
    }
    onChange(chosen.has(id) ? value.filter((v) => v !== id) : [...value, id]);
  };
  // Asks for the next page when the list is scrolled within a row of its end.
  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 48 && results.hasNextPage && !results.isFetchingNextPage) void results.fetchNextPage();
  };

  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      {showChosen && value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((id) => {
            const o = known.get(id);
            // A stored value the service no longer offers (removed, or saved as a name) shows as itself so it can be removed.
            const missing = !labels.isPending && !o;
            return (
              <Badge key={id} variant="outline" className={cn('gap-1.5 bg-card py-1 pr-1 pl-2.5 text-sm font-normal', missing && 'border-dashed text-muted-foreground')} title={missing ? 'Not found; remove it or pick it again.' : (o?.hint ?? undefined)}>
                {Icon && <Icon className="size-3.5 text-muted-foreground" />}
                {o?.label ?? id}
                {!disabled && (
                  <button type="button" className="rounded-sm p-0.5 hover:bg-foreground/10" onClick={() => onChange(value.filter((v) => v !== id))} aria-label={`Remove ${o?.label ?? id}`}>
                    <X className="size-3" />
                  </button>
                )}
              </Badge>
            );
          })}
        </div>
      )}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" size="sm" className="self-start bg-card" disabled={disabled} aria-haspopup="listbox">
            <Plus className="size-3.5" /> {addLabel}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-(--radix-popover-trigger-width) min-w-72 p-0 sm:min-w-96" align="start">
          {/* Filtering is the server's: cmdk's own filter would hide rows the search already chose. */}
          <Command shouldFilter={false}>
            <CommandInput value={search} onValueChange={setSearch} placeholder={searchPlaceholder} />
            <CommandList onScroll={onScroll} className="max-h-72">
              {results.isPending ? (
                <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Searching…
                </div>
              ) : results.isError ? (
                <p className="px-3 py-6 text-sm text-destructive">Couldn’t search. Try again.</p>
              ) : (
                <>
                  <CommandEmpty>{emptyText}</CommandEmpty>
                  <CommandGroup>
                    {options.map((o) => (
                      <CommandItem key={o.id} value={o.id} disabled={!!o.disabled} onSelect={() => pick(o.id)} className="flex items-start gap-2">
                        <Check className={cn('mt-0.5 size-4 shrink-0', chosen.has(o.id) ? 'opacity-100' : 'opacity-0')} />
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate">{o.label}</span>
                          {(o.disabled || o.hint) && <span className="truncate text-xs text-muted-foreground">{o.disabled ?? o.hint}</span>}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                  {results.isFetchingNextPage && (
                    <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                      <Loader2 className="size-3 animate-spin" /> Loading more…
                    </div>
                  )}
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
