'use client';

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { useSourceScopes } from '@/hooks/knowledge-queries';
import type { ScopeOption } from '@/lib/types/knowledge';

const SEARCH_DEBOUNCE_MS = 300;

/**
 * Picks an input's values from what the source's app holds, as its scopes tool answers through kb-service: searched by
 * name, and also whatever each value already picked in another picker holds (a picked site's libraries). Only scopes of
 * `kind` are offered. Nothing here knows an app: the kind and the parents come from the plugin's declared inputs.
 */
export function ScopePicker({
  id,
  plugin,
  source,
  kind,
  parents,
  value,
  onChange,
  onNames,
  disabled,
}: {
  id: string;
  plugin: string;
  source: string;
  kind: string;
  parents: string[];
  value: string[];
  onChange: (v: string[]) => void;
  /** Told the name shown for each picked id on every pick, so a caller can keep names beside the ids. */
  onNames?: (names: Record<string, string>) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = React.useState('');
  const [searched, setSearched] = React.useState('');
  React.useEffect(() => {
    const t = setTimeout(() => setSearched(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);
  const found = useSourceScopes({ plugin, source, query: searched }, !disabled);
  const held = parents.slice(0, 5);
  const options = useHeldScopes(plugin, source, held, searched, !disabled);
  const pending = found.isPending || options.pending;
  const offered = dedupe([...(found.data?.scopes ?? []), ...options.scopes]).filter((s) => s.kind === kind);
  const picked = new Set(value);
  const kinds = kind.endsWith('y') ? `${kind.slice(0, -1)}ies` : `${kind}s`;
  // Titles of every scope seen, so a pick the current search hides is still named, not shown by its id.
  const seen = React.useRef(new Map<string, string>());
  for (const s of offered) seen.current.set(s.id, s.title);
  const hidden = value.filter((v) => !offered.some((s) => s.id === v));
  const pick = (next: string[]) => {
    onChange(next);
    onNames?.(Object.fromEntries(next.flatMap((v) => (seen.current.has(v) ? [[v, seen.current.get(v)!]] : []))));
  };
  const toggle = (s: ScopeOption) => pick(picked.has(s.id) ? value.filter((v) => v !== s.id) : [...value, s.id]);
  const error = found.error ?? options.error;
  return (
    <div className="flex flex-col gap-2" data-testid={`${id}-picker`}>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {picked.size} picked{offered.length ? ` · ${offered.length} listed` : ''}
        </span>
        <span className="flex gap-1">
          <Button variant="ghost" size="sm" className="h-7" disabled={disabled || !offered.length} onClick={() => pick([...new Set([...value, ...offered.map((s) => s.id)])])}>
            Select all
          </Button>
          <Button variant="ghost" size="sm" className="h-7" disabled={disabled || !value.length} onClick={() => pick([])}>
            Clear
          </Button>
        </span>
      </div>
      <Command shouldFilter={false} className="rounded-md border">
        <CommandInput id={id} placeholder={`Search ${kinds} by name…`} value={query} onValueChange={setQuery} aria-label={`Search ${kinds}`} disabled={disabled} />
        <CommandList className="max-h-64">
          {pending ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">Asking the app for its {kinds}…</p>
          ) : error ? (
            <p className="px-3 py-6 text-center text-sm text-destructive-text">Couldn’t list the {kinds}: {(error as Error).message}</p>
          ) : (
            <>
              <CommandEmpty>{searched ? `No ${kind} called “${searched}” that this connection can read.` : `No ${kind} this connection can read.`}</CommandEmpty>
              <CommandGroup>
                {offered.map((s) => (
                  <CommandItem key={s.id} value={s.id} onSelect={() => toggle(s)} className="gap-3" data-testid={`${id}-option`}>
                    <Checkbox checked={picked.has(s.id)} aria-label={s.title} className="pointer-events-none" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{s.title}</span>
                      {s.detail && <span className="block truncate text-xs text-muted-foreground">{s.detail}</span>}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
        </CommandList>
      </Command>
      {hidden.length > 0 && <p className="text-xs text-muted-foreground">Also picked: {hidden.map((v) => seen.current.get(v) ?? v).join(', ')}</p>}
    </div>
  );
}

/** What each picked parent holds, one query per parent (at most five, so the picker stays a few calls). */
/** What each picked parent holds, searched by the scopes tool on the server like the main list. */
function useHeldScopes(plugin: string, source: string, parents: string[], query: string, enabled: boolean) {
  const a = useSourceScopes({ plugin, source, parent: parents[0] ?? '', query }, enabled && parents.length > 0);
  const b = useSourceScopes({ plugin, source, parent: parents[1] ?? '', query }, enabled && parents.length > 1);
  const c = useSourceScopes({ plugin, source, parent: parents[2] ?? '', query }, enabled && parents.length > 2);
  const d = useSourceScopes({ plugin, source, parent: parents[3] ?? '', query }, enabled && parents.length > 3);
  const e = useSourceScopes({ plugin, source, parent: parents[4] ?? '', query }, enabled && parents.length > 4);
  const asked = [a, b, c, d, e].slice(0, parents.length);
  return {
    scopes: asked.flatMap((q) => q.data?.scopes ?? []),
    pending: asked.some((q) => q.isPending),
    error: asked.find((q) => q.error)?.error ?? null,
  };
}

const dedupe = (rows: ScopeOption[]) => [...new Map(rows.map((r) => [r.id, r])).values()];
