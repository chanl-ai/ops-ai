'use client';

import * as React from 'react';
import { Check, ChevronDown, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

export interface PickerItem {
  value: string;
  label: string;
  /** One line under the label. */
  description?: string;
  /** Greyed out and not pickable; with `checked` it reads as already chosen. */
  disabled?: boolean;
  checked?: boolean;
  testId?: string;
}
export interface PickerGroup {
  heading: string;
  items: PickerItem[];
}

/**
 * A button that opens a searchable list in named groups, one pick per click. For a short list the page already holds
 * (a workspace's sections); a list that grows with the team is searched on the server (EntityPicker, SearchSelect).
 * `state` draws the list's own loading and error rows in place of the groups.
 */
export function GroupedPicker({
  label,
  searchPlaceholder = 'Search',
  groups,
  onPick,
  state = 'ready',
  onRetry,
  emptyText = 'Nothing matches.',
  testId,
}: {
  label: string;
  searchPlaceholder?: string;
  groups: PickerGroup[];
  onPick: (value: string) => void;
  state?: 'ready' | 'loading' | 'error';
  onRetry?: () => void;
  emptyText?: string;
  testId?: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="justify-between" data-testid={testId}>
          <span className="inline-flex items-center gap-1.5">
            <Plus className="size-3.5" /> {label}
          </span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(22rem,calc(100vw-2rem))] p-0">
        {state === 'loading' ? (
          <p className="p-3 text-sm text-muted-foreground" role="status">
            Loading…
          </p>
        ) : state === 'error' ? (
          <div className="flex flex-col items-start gap-2 p-3 text-sm">
            <p>Couldn’t read the list.</p>
            {onRetry && (
              <Button type="button" variant="outline" size="sm" onClick={onRetry}>
                Try again
              </Button>
            )}
          </div>
        ) : (
          <Command>
            <CommandInput placeholder={searchPlaceholder} />
            <CommandList>
              <CommandEmpty>{emptyText}</CommandEmpty>
              {groups.map((g) => (
                <CommandGroup key={g.heading} heading={g.heading}>
                  {g.items.map((item) => (
                    <CommandItem
                      key={item.value}
                      value={item.label}
                      disabled={item.disabled}
                      onSelect={() => {
                        onPick(item.value);
                        setOpen(false);
                      }}
                      data-testid={item.testId}
                    >
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="block">{item.label}</span>
                        {item.description && <span className="block truncate text-xs text-muted-foreground">{item.description}</span>}
                        {item.checked && <span className="sr-only">Already added</span>}
                      </span>
                      {item.checked && <Check className="size-4 text-muted-foreground" aria-hidden />}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        )}
      </PopoverContent>
    </Popover>
  );
}
