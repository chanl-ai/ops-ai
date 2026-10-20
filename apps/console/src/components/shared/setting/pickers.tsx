'use client';

import * as React from 'react';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface PickerOption {
  value: string;
  label: string;
  hint?: string;
}

function List({ options, selected, onPick, noun }: { options: PickerOption[]; selected: string[]; onPick: (v: string) => void; noun: string }) {
  return (
    <Command>
      <CommandInput placeholder={`Search ${noun}…`} />
      <CommandList>
        <CommandEmpty>No {noun} found.</CommandEmpty>
        <CommandGroup>
          {options.map((o) => (
            <CommandItem key={o.value} value={`${o.label} ${o.hint ?? ''}`} onSelect={() => onPick(o.value)}>
              <Check className={cn('size-4', selected.includes(o.value) ? 'opacity-100' : 'opacity-0')} />
              <span className="flex-1">{o.label}</span>
              {o.hint && <span className="text-xs text-muted-foreground">{o.hint}</span>}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </Command>
  );
}

/** Pick one of many by searching: a team, an agent, a model alias. */
export function Combobox({ options, value, onChange, noun, placeholder, id }: { options: PickerOption[]; value: string | null; onChange: (v: string) => void; noun: string; placeholder?: string; id?: string }) {
  const [open, setOpen] = React.useState(false);
  const current = options.find((o) => o.value === value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button id={id} type="button" variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between bg-card font-normal">
          <span className={cn('truncate', !current && 'text-muted-foreground')}>{current?.label ?? placeholder ?? `Choose ${noun}`}</span>
          <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <List
          options={options}
          selected={value ? [value] : []}
          noun={noun}
          onPick={(v) => {
            onChange(v);
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

/** Pick several by searching; the choices show as removable chips under the field. */
export function MultiSelect({ options, value, onChange, noun, placeholder }: { options: PickerOption[]; value: string[]; onChange: (v: string[]) => void; noun: string; placeholder?: string }) {
  const [open, setOpen] = React.useState(false);
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div className="flex flex-col gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between bg-card font-normal">
            <span className={cn('truncate', !value.length && 'text-muted-foreground')}>{value.length ? `${value.length} selected` : (placeholder ?? `Choose ${noun}`)}</span>
            <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
          <List options={options} selected={value} noun={noun} onPick={toggle} />
        </PopoverContent>
      </Popover>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((v) => (
            <Badge key={v} variant="secondary" className="gap-1 font-normal">
              {options.find((o) => o.value === v)?.label ?? v}
              <button type="button" aria-label={`Remove ${options.find((o) => o.value === v)?.label ?? v}`} onClick={() => toggle(v)} className="rounded-sm hover:text-foreground">
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
