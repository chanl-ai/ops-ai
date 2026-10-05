'use client';

import * as React from 'react';
import { Check, ChevronDown, ShieldCheck, User, UserRound, Users, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { RunAsPrincipal } from '@/lib/types/run-as';
import { cn } from '@/lib/utils';

const CLEARANCE: Record<RunAsPrincipal['clearance'], string> = {
  internal: 'Internal documents only',
  confidential: 'Up to confidential',
  restricted: 'Up to restricted',
};

/**
 * Picks the staff member or role to run as. Adapted from the shared component library's session config panel (popover with a
 * searchable command list), grouped into people and roles.
 */
function RunAsPicker({ principals, value, onChange, loading, id }: { principals: RunAsPrincipal[]; value: RunAsPrincipal | null; onChange: (id: string | null) => void; loading: boolean; id: string }) {
  const [open, setOpen] = React.useState(false);
  const pick = (pid: string | null) => {
    onChange(pid);
    setOpen(false);
  };
  const people = principals.filter((p) => p.kind === 'person');
  const roles = principals.filter((p) => p.kind === 'role');
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button id={id} variant="outline" role="combobox" aria-expanded={open} className="h-9 w-full justify-between font-normal sm:w-64" data-testid="run-as-picker">
          <span className="flex min-w-0 items-center gap-2">
            {value?.kind === 'role' ? <Users className="size-4 text-muted-foreground" /> : <UserRound className="size-4 text-muted-foreground" />}
            <span className="truncate">{value ? value.name : loading ? 'Loading…' : 'Yourself · your own access'}</span>
          </span>
          <ChevronDown className="size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(22rem,calc(100vw-2rem))] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search people and roles…" />
          <CommandList>
            <CommandEmpty>No one matches.</CommandEmpty>
            <CommandGroup>
              <CommandItem value="yourself own access" onSelect={() => pick(null)}>
                <User />
                <span className="flex-1">Yourself · your own access</span>
                {!value && <Check className="size-4" />}
              </CommandItem>
            </CommandGroup>
            {[
              { label: 'People', list: people },
              { label: 'Roles', list: roles },
            ].map(({ label, list }) =>
              list.length ? (
                <CommandGroup key={label} heading={label}>
                  {list.map((p) => (
                    <CommandItem key={p.id} value={`${p.name} ${p.title} ${p.team}`} onSelect={() => pick(p.id)} data-testid={`run-as-option-${p.id}`}>
                      {p.kind === 'role' ? <Users /> : <UserRound />}
                      <div className="min-w-0 flex-1">
                        <div className="truncate">{p.name}</div>
                        <div className="truncate text-xs text-muted-foreground">
                          {p.title} · {p.team}
                        </div>
                      </div>
                      {value?.id === p.id && <Check className="size-4" />}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ) : null,
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/**
 * States who a test runs as and what they are entitled to, before any answer. Adapted from the shared
 * component library's client context bar: one labelled control row on a card, with the status meta on its own line.
 */
export function RunAsBar({
  principals,
  loading,
  value,
  onChange,
  className,
}: {
  principals: RunAsPrincipal[];
  loading: boolean;
  value: string | null;
  onChange: (id: string | null) => void;
  className?: string;
}) {
  const selected = principals.find((p) => p.id === value) ?? null;
  const id = React.useId();
  return (
    <Card className={cn('min-w-0 gap-0 py-0', className)} data-testid="run-as-bar">
      <CardContent className="flex min-w-0 flex-col gap-2 px-4 py-2.5">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={id} className="text-xs text-muted-foreground">
              Running as
            </label>
            <div className="flex items-center gap-1">
              <RunAsPicker id={id} principals={principals} value={selected} onChange={onChange} loading={loading} />
              {selected && (
                <Button variant="ghost" size="icon" className="size-9" onClick={() => onChange(null)} aria-label="Run as yourself">
                  <X className="size-4" />
                </Button>
              )}
            </div>
          </div>
          {selected && (
            <div className="flex max-w-full min-w-0 flex-1 basis-48 flex-wrap gap-1 pb-1.5" aria-label="Entitlements">
              {selected.entitlements.map((e) => (
                <Badge key={e} variant="outline" className="max-w-full min-w-0 shrink font-normal" title={e}>
                  <span className="truncate">{e}</span>
                </Badge>
              ))}
            </div>
          )}
        </div>
        <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs break-words text-muted-foreground">
          <ShieldCheck className="size-3.5" aria-hidden />
          {selected ? (
            <>
              {selected.title} · {selected.team} · reads {selected.collections ? selected.collections.join(', ') : 'every collection'} · {CLEARANCE[selected.clearance].toLowerCase()} ·{' '}
              {selected.tools ? `${selected.tools.length} ${selected.tools.length === 1 ? 'tool' : 'tools'}` : 'every tool'}
            </>
          ) : (
            'Answers use your own access. Choose a person or role to see what they would get.'
          )}
        </span>
      </CardContent>
    </Card>
  );
}
