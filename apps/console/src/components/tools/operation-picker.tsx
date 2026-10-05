'use client';

import * as React from 'react';
import { Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ToolAccess } from '@/lib/types/domain';
import type { DiscoveredOperation } from '@/lib/types/tool-modules';

const ACCESS_OPTIONS: { value: ToolAccess; label: string }[] = [
  { value: 'read', label: 'Read' },
  { value: 'write', label: 'Write' },
  { value: 'money_movement', label: 'Moves money' },
];

/**
 * Choose which discovered operations the module exposes, and confirm each one's access class. Grouped by
 * resource, as in the shared component library's install picker; the access class decides approval and four-eyes, so it is editable
 * here rather than trusted from the server's own description.
 */
export function OperationPicker({
  operations,
  selected,
  onChange,
}: {
  operations: DiscoveredOperation[];
  /** Selected operation name → confirmed access class. */
  selected: Map<string, ToolAccess>;
  onChange: (next: Map<string, ToolAccess>) => void;
}) {
  const [q, setQ] = React.useState('');
  const shown = operations.filter((o) => !q || `${o.name} ${o.description} ${o.path ?? ''}`.toLowerCase().includes(q.toLowerCase()));
  const groups = [...new Set(shown.map((o) => o.group))];
  const toggle = (o: DiscoveredOperation, on: boolean) => {
    const next = new Map(selected);
    if (on) next.set(o.name, selected.get(o.name) ?? o.access);
    else next.delete(o.name);
    onChange(next);
  };
  const setAccess = (name: string, a: ToolAccess) => onChange(new Map(selected).set(name, a));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-40 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Filter ${operations.length} operations…`} aria-label="Filter operations" className="h-8 pl-8" />
        </div>
        <span className="text-sm font-medium tabular-nums">
          {selected.size} of {operations.length} selected
        </span>
        <div className="flex gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(new Map(operations.map((o) => [o.name, selected.get(o.name) ?? o.access])))}>
            Select all
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(new Map())}>
            Clear
          </Button>
        </div>
      </div>
      {!shown.length && <p className="py-6 text-center text-sm text-muted-foreground">No operations match “{q}”.</p>}
      {groups.map((g) => (
        <div key={g} className="flex flex-col gap-1">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{g}</p>
          <div className="divide-y rounded-lg border">
            {shown
              .filter((o) => o.group === g)
              .map((o) => {
                const on = selected.has(o.name);
                return (
                  <div key={o.name} className="flex items-center gap-3 px-3 py-2">
                    <Checkbox id={`op-${o.name}`} checked={on} onCheckedChange={(v) => toggle(o, !!v)} />
                    <label htmlFor={`op-${o.name}`} className="min-w-0 flex-1 cursor-pointer">
                      <code className="font-mono text-sm">{o.name}</code>
                      <span className="block truncate text-xs text-muted-foreground">
                        {o.method && (
                          <span className="font-mono">
                            {o.method} {o.path}
                            {' · '}
                          </span>
                        )}
                        {o.description}
                      </span>
                    </label>
                    <Select value={selected.get(o.name) ?? o.access} onValueChange={(v) => setAccess(o.name, v as ToolAccess)} disabled={!on}>
                      <SelectTrigger size="sm" className="w-36" aria-label={`Access for ${o.name}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ACCESS_OPTIONS.map((a) => (
                          <SelectItem key={a.value} value={a.value}>
                            {a.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                );
              })}
          </div>
        </div>
      ))}
    </div>
  );
}
