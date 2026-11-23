'use client';

import * as React from 'react';
import { Search } from 'lucide-react';

import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useDiscoveredNames, useDiscoveredOperations } from '@/hooks/tool-module-queries';
import { plural } from '@/lib/format';
import type { ToolAccess } from '@/lib/types/domain';
import type { DiscoveredOperationRow } from '@/lib/types/tool-modules';

const ACCESS_OPTIONS: { value: ToolAccess; label: string }[] = [
  { value: 'read', label: 'Read' },
  { value: 'write', label: 'Write' },
];

/**
 * Choose which discovered operations the module exposes, and confirm each one's access class. The operations are the
 * stored discovery's, searched on the server and read a page at a time; select-all asks the server for every matching
 * name, so it covers operations not loaded yet. Grouped by resource, as in the shared component library's install
 * picker; the access class decides approval and four-eyes, so it is editable here rather than trusted from the
 * server's own description. An operation the module already has (`added`) is shown but never selected.
 */
export function OperationPicker({
  discoveryId,
  total,
  selected,
  onChange,
}: {
  discoveryId: string;
  /** How many operations the source lists. */
  total: number;
  /** Selected operation name → confirmed access class. */
  selected: Map<string, ToolAccess>;
  onChange: (next: Map<string, ToolAccess>) => void;
}) {
  const [q, setQ] = React.useState('');
  const list = useDiscoveredOperations(discoveryId, { search: q });
  const names = useDiscoveredNames();
  const shown = list.rows;
  const fresh = (list.total ?? 0) - list.addedTotal;
  const groups = [...new Set(shown.map((o) => o.group))];
  const toggle = (o: DiscoveredOperationRow, on: boolean) => {
    const next = new Map(selected);
    if (on) next.set(o.name, selected.get(o.name) ?? o.access);
    else next.delete(o.name);
    onChange(next);
  };
  const setAccess = (name: string, a: ToolAccess) => onChange(new Map(selected).set(name, a));
  const selectAll = async () => {
    const all = await names.mutateAsync({ discoveryId, search: q.trim() || undefined });
    const next = new Map(selected);
    for (const o of all) next.set(o.name, selected.get(o.name) ?? o.access);
    onChange(next);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-40 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${plural(total, 'operation')}…`} aria-label="Search operations" className="h-8 pl-8" />
        </div>
        <span className="text-sm font-medium tabular-nums" data-testid="op-selected-count">
          {selected.size} selected{list.total !== undefined && ` · ${fresh} ${list.addedTotal ? 'new ' : ''}${q.trim() ? 'matching' : 'in all'}`}
        </span>
        <div className="flex gap-1">
          <LoadingButton type="button" variant="ghost" size="sm" isLoading={names.isPending} loadingText="Selecting…" onClick={selectAll} disabled={!fresh}>
            Select all
          </LoadingButton>
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(new Map())} disabled={!selected.size}>
            Clear
          </Button>
        </div>
      </div>
      {list.isError && <p className="py-6 text-center text-sm text-destructive">The operations could not be read. Go back and read the source again.</p>}
      {list.isPending && (
        <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading operations">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}
      {!list.isPending && !list.isError && !shown.length && <p className="py-6 text-center text-sm text-muted-foreground">{q.trim() ? `No operations match “${q.trim()}”.` : 'The source lists no operations.'}</p>}
      {groups.map((g) => (
        <div key={g} className="flex flex-col gap-1">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{g}</p>
          <div className="divide-y rounded-lg border">
            {shown
              .filter((o) => o.group === g)
              .map((o) => {
                const on = !o.added && selected.has(o.name);
                return (
                  <div key={o.name} className="flex items-center gap-3 px-3 py-2" data-testid={o.added ? `op-in-module-${o.name}` : undefined}>
                    <Checkbox id={`op-${o.name}`} checked={on} disabled={o.added} onCheckedChange={(v) => toggle(o, !!v)} />
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
                    {o.added && <span className="text-xs text-muted-foreground">Already here</span>}
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
      {list.hasNextPage && <p className="text-center text-xs text-muted-foreground tabular-nums">Showing {shown.length} of {list.total}</p>}
      {list.hasNextPage && (
        <LoadingButton type="button" variant="outline" size="sm" className="self-center" isLoading={list.isFetchingNextPage} loadingText="Loading…" onClick={() => list.fetchNextPage()} data-testid="op-show-more">
          Show more
        </LoadingButton>
      )}
    </div>
  );
}
