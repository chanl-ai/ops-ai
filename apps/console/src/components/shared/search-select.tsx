'use client';

import * as React from 'react';
import { Check, ChevronsUpDown, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandInput, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { type OptionSource, useOptionSearch } from '@/hooks/options-queries';
import type { OptionsPage } from '@/lib/types/query';
import { cn } from '@/lib/utils';

/**
 * Pick one entity from an `/options` source: the search runs on the server as the person types and the list pages in
 * as it scrolls, so a team with hundreds of choices never loads them all. The trigger shows the chosen one's label,
 * which the caller already holds (a stored choice is shown by name, not looked up in a list). `noneLabel` adds a
 * first row that clears the choice.
 */
export function SearchSelect<P extends OptionsPage = OptionsPage>({
  source,
  value,
  onChange,
  placeholder,
  searchPlaceholder = 'Search…',
  emptyText = 'Nothing matches.',
  noneLabel,
  renderOption,
  disabled,
  className,
  testId,
  ariaLabel,
  error,
}: {
  source: OptionSource<P>;
  value: { id: string; label: string } | null;
  onChange: (id: string, option: P['data'][number] | null) => void;
  placeholder: string;
  searchPlaceholder?: string;
  emptyText?: string;
  noneLabel?: string;
  renderOption?: (o: P['data'][number]) => React.ReactNode;
  disabled?: boolean;
  className?: string;
  testId?: string;
  ariaLabel?: string;
  /** Shown in the trigger in place of the choice when the first read failed. */
  error?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const results = useOptionSearch(source, search, open);
  const options = (results.data?.pages ?? []).flatMap((p) => p.data);
  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 48 && results.hasNextPage && !results.isFetchingNextPage) void results.fetchNextPage();
  };
  const choose = (id: string, o: P['data'][number] | null) => {
    onChange(id, o);
    setOpen(false);
  };
  return (
    <Popover open={open} onOpenChange={(o) => (setOpen(o), o || setSearch(''))}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" role="combobox" aria-expanded={open} aria-label={ariaLabel} disabled={disabled} className={cn('justify-between bg-card font-normal', className)} data-testid={testId}>
          {error ? (
            <span className="truncate text-destructive-text">{error}</span>
          ) : value ? (
            <span className="truncate">{value.label}</span>
          ) : (
            <span className="truncate text-muted-foreground">{placeholder}</span>
          )}
          <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) min-w-72 p-0" align="start">
        {/* Filtering is the server's: cmdk's own filter would hide rows the search already chose. */}
        <Command shouldFilter={false}>
          <CommandInput value={search} onValueChange={setSearch} placeholder={searchPlaceholder} data-testid={testId ? `${testId}-search` : undefined} />
          <CommandList onScroll={onScroll} className="max-h-72">
            {results.isPending ? (
              <div className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Searching…
              </div>
            ) : results.isError ? (
              <p className="px-3 py-6 text-sm text-destructive-text">Couldn’t search. Try again.</p>
            ) : (
              <>
                <CommandEmpty>{emptyText}</CommandEmpty>
                <CommandGroup>
                  {noneLabel && !search && (
                    <CommandItem value="__none__" onSelect={() => choose('', null)}>
                      <Check className={cn('size-4 shrink-0', value ? 'opacity-0' : 'opacity-100')} />
                      {noneLabel}
                    </CommandItem>
                  )}
                  {options.map((o) => (
                    <CommandItem key={o.id} value={o.id} disabled={!!o.disabled} onSelect={() => choose(o.id, o)} data-testid={testId ? `${testId}-option-${o.id}` : undefined}>
                      <Check className={cn('size-4 shrink-0', value?.id === o.id ? 'opacity-100' : 'opacity-0')} />
                      {renderOption ? renderOption(o) : <span className="truncate">{o.label}</span>}
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
  );
}
