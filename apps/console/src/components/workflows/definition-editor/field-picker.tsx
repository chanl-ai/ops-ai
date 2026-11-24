'use client';

import * as React from 'react';
import { CornerDownRight, X } from 'lucide-react';

import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import type { SampleStep } from '@/lib/types/engine';

/**
 * What the step on screen can read, from the sample route: the earlier steps with their fields and last values. The
 * step sheet provides it once, so every mapping field in the form (lists and named values included) shares one read.
 */
export interface FieldSource {
  steps: SampleStep[];
  loading: boolean;
  /** The sample read failed: the picker and What it gives show it with Retry, as What it receives does. */
  error?: unknown;
  retry?: () => void;
  retrying?: boolean;
  /** The working copy does not hold this step yet: its fields list once the autosave lands. */
  unsaved: boolean;
  /** Every step of the workflow by id, to name a chip whose path the sample does not list. */
  names: Record<string, string>;
  /** A viewer reads the chips and gets no picker. */
  readOnly?: boolean;
}

const EMPTY: FieldSource = { steps: [], loading: false, unsaved: false, names: {} };
export const FieldSourceContext = React.createContext<FieldSource>(EMPTY);

export const SAVE_FIRST = "Save the workflow to list this step's fields.";

/** The step a `$.nodes.<id>.out…` path reads; `$.input…` reads the trigger. */
function stepOf(path: string): string | null {
  const parts = path.replace(/^\$\./, '').split('.');
  return parts[0] === 'nodes' && parts.length > 1 ? parts[1] : null;
}

/** How a stored path reads to a person: "Step → Field", or "Missing step" when the step it names is gone. */
export function chipFor(path: string, source: FieldSource): { label: string; sample: string | null; missing: boolean } {
  for (const s of source.steps) {
    const f = s.fields.find((x) => x.path === path);
    if (f) return { label: `${s.name} → ${f.label}`, sample: f.sample, missing: false };
  }
  const step = stepOf(path);
  const rest = path.split('.').slice(step ? 4 : 2).join(' ');
  if (step === null) return { label: `Run input → ${rest || 'all of it'}`, sample: null, missing: false };
  const name = source.names[step];
  if (!name) return { label: 'Missing step', sample: null, missing: true };
  return { label: `${name} → ${rest || 'all of it'}`, sample: null, missing: false };
}

/** A picked value: the step and field by name, with last run's value under it. `fieldId` lets a problem's Fix focus it. */
export function FieldChip({ path, onClear, readOnly, fieldId }: { path: string; onClear: () => void; readOnly?: boolean; fieldId?: string }) {
  const source = React.useContext(FieldSourceContext);
  const chip = chipFor(path, source);
  return (
    <div className="flex min-w-0 items-start gap-2 rounded-md border px-2 py-1.5" data-testid="field-chip" data-field={fieldId} tabIndex={fieldId ? -1 : undefined}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Badge variant={chip.missing ? 'destructive' : 'secondary'} className="max-w-full justify-start truncate">
          <CornerDownRight className="size-3" /> <span className="truncate">{chip.label}</span>
        </Badge>
        {chip.sample !== null && <span className="truncate text-xs text-muted-foreground">Sample: {chip.sample}</span>}
      </div>
      {!readOnly && (
        <Button type="button" id={fieldId} variant="ghost" size="icon" aria-label="Clear the field" onClick={onClear}>
          <X />
        </Button>
      )}
    </div>
  );
}

/** "Use a field…": earlier steps' fields grouped by step, searched by name, with last run's value beside each. */
export function FieldPicker({ onPick, label = 'Use a field…' }: { onPick: (path: string) => void; label?: string }) {
  const source = React.useContext(FieldSourceContext);
  const [open, setOpen] = React.useState(false);
  const groups = source.steps.filter((s) => s.fields.length > 0);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" data-testid="field-picker-open">
          <CornerDownRight className="size-4" /> {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(24rem,calc(100vw-2rem))] p-0" align="start" data-testid="field-picker">
        <Command>
          <CommandInput placeholder="Search fields…" />
          <CommandList>
            {source.loading ? (
              <div className="flex flex-col gap-2 p-3" data-testid="field-picker-loading">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            ) : source.error ? (
              <div className="p-3">
                <QueryError what="this step's fields" error={source.error} onRetry={() => source.retry?.()} retrying={source.retrying} testId="field-picker-error" />
              </div>
            ) : source.unsaved ? (
              <p className="p-3 text-sm text-muted-foreground">{SAVE_FIRST}</p>
            ) : groups.length === 0 ? (
              <p className="p-3 text-sm text-muted-foreground">No earlier step gives a field yet.</p>
            ) : (
              <>
                <CommandEmpty>Nothing matches.</CommandEmpty>
                {groups.map((s) => (
                  <CommandGroup key={s.id} heading={s.name}>
                    {s.fields.map((f) => (
                      <CommandItem
                        key={f.path}
                        // Searched by the words a person reads; the step's id keeps two steps of one name apart.
                        value={`${s.name} ${f.label} ${f.name} ${s.id}`}
                        onSelect={() => {
                          onPick(f.path);
                          setOpen(false);
                        }}
                      >
                        <span className="min-w-0 flex-1 truncate">{f.label}</span>
                        {f.sample !== null && <span className="max-w-[45%] truncate text-xs text-muted-foreground">{f.sample}</span>}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ))}
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
