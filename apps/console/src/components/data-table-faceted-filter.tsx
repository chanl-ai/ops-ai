import * as React from 'react';
import { PlusCircledIcon } from '@radix-ui/react-icons';
import { Column } from '@tanstack/react-table';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Separator } from '@/components/ui/separator';

interface DataTableFacetedFilterProps<TData, TValue> {
  column?: Column<TData, TValue>;
  title?: string;
  options: {
    label: string;
    value: string;
    icon?: React.ComponentType<{ className?: string }>;
    /**
     * How many records carry this value, counted by the API. Never derive it
     * from the loaded page — a facet whose options span the whole workspace
     * would then report a count for one page of it.
     */
    count?: number;
  }[];
  /**
   * Force the search box on or off. Defaults to a size heuristic, which is
   * wrong for facets that grow over time — the tag vocabulary gains an entry
   * per import, so it should opt in regardless of how few tags exist today.
   */
  searchable?: boolean;
}

export function DataTableFacetedFilter<TData, TValue>({
  column,
  title,
  options,
  searchable,
}: DataTableFacetedFilterProps<TData, TValue>) {
  const [open, setOpen] = React.useState(false);

  // What is actually filtering right now. The trigger reads from this, never
  // from the draft — the button must not claim a filter is active before it is.
  // Rebuilt each render rather than memoised: these are facet-sized arrays, and
  // memoising on a joined key needed a lint suppression to hide a dependency
  // the rule could not verify.
  const committed = new Set((column?.getFilterValue() as string[]) ?? []);

  /**
   * Selection is STAGED while the popover is open and committed once, on close.
   *
   * Committing per click made every checkbox a server round-trip: these facets
   * drive server-side query params, so picking four tags fired four requests
   * and four page resets, and the list flickered under the cursor. Staging
   * makes a multi-select cost exactly one request, however it is dismissed —
   * Apply, click-outside, and Escape all commit the same draft.
   */
  const [draft, setDraft] = React.useState<Set<string>>(committed);

  const commit = React.useCallback(
    (next: Set<string>) => {
      const values = Array.from(next);
      const current = (column?.getFilterValue() as string[]) ?? [];
      // Opening and closing without changing anything must not cost a request.
      const unchanged =
        values.length === current.length && values.every((v) => current.includes(v));
      if (unchanged) return;
      column?.setFilterValue(values.length ? values : undefined);
    },
    [column]
  );

  const handleOpenChange = (next: boolean) => {
    if (next) {
      // Re-seed from the live filter so a reopened popover reflects reality.
      setDraft(new Set((column?.getFilterValue() as string[]) ?? []));
    } else {
      commit(draft);
    }
    setOpen(next);
  };

  const toggle = (value: string) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const showSearch = searchable ?? options.length > 6;
  const dirty = draft.size !== committed.size || Array.from(draft).some((v) => !committed.has(v));

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 border-dashed">
          <PlusCircledIcon className="mr-2 h-4 w-4" />
          {title}
          {committed.size > 0 && (
            <>
              <Separator orientation="vertical" className="mx-2 h-4" />
              <Badge variant="secondary" className="rounded-sm px-1 font-normal lg:hidden">
                {committed.size}
              </Badge>
              <div className="hidden space-x-1 lg:flex">
                {committed.size > 2 ? (
                  <Badge variant="secondary" className="rounded-sm px-1 font-normal">
                    {committed.size} selected
                  </Badge>
                ) : (
                  options
                    .filter((option) => committed.has(option.value))
                    .map((option) => (
                      <Badge
                        variant="secondary"
                        key={option.value}
                        className="rounded-sm px-1 font-normal"
                      >
                        {option.label}
                      </Badge>
                    ))
                )}
              </div>
            </>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[240px] p-0" align="start">
        <Command>
          {showSearch && (
            <CommandInput placeholder={`Search ${title?.toLowerCase() ?? 'options'}…`} />
          )}
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const isSelected = draft.has(option.value);
                return (
                  <CommandItem
                    key={option.value}
                    value={option.label}
                    onSelect={() => toggle(option.value)}
                    data-testid={`facet-option-${option.value}`}
                    // The Checkbox below is aria-hidden, so nothing else conveys
                    // selected-state to a screen reader: CommandItem renders as a
                    // plain option and the label alone reads identically checked
                    // or unchecked. This carries the state the checkbox shows.
                    aria-label={`${option.label}, ${isSelected ? 'selected' : 'not selected'}`}
                  >
                    {/*
                      The shared Checkbox — not a hand-rolled div. This facet
                      used to reimplement one, which is how it drifted into its
                      own contrast bug. Presentational only: CommandItem owns
                      the click, so this must not take pointer events or focus.
                    */}
                    <Checkbox
                      checked={isSelected}
                      className="mr-2 pointer-events-none"
                      tabIndex={-1}
                      aria-hidden="true"
                    />
                    {option.icon && <option.icon className="mr-2 h-4 w-4 text-muted-foreground" />}
                    <span className="truncate">{option.label}</span>
                    {option.count !== undefined && (
                      <span
                        className="ml-auto pl-2 text-xs tabular-nums text-muted-foreground"
                        data-testid={`facet-count-${option.value}`}
                      >
                        {option.count}
                      </span>
                    )}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>

          <CommandSeparator />
          <div className="flex items-center justify-between gap-2 p-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              disabled={draft.size === 0}
              onClick={() => setDraft(new Set())}
              data-testid="facet-clear"
            >
              Clear
            </Button>
            <span className="text-xs text-muted-foreground" data-testid="facet-draft-count">
              {draft.size} selected
            </span>
            <Button
              size="sm"
              className="h-7 px-3"
              onClick={() => handleOpenChange(false)}
              data-testid="facet-apply"
            >
              {dirty ? 'Apply' : 'Done'}
            </Button>
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
