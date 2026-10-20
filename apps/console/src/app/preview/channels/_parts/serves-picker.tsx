'use client';

import { toast } from 'sonner';

import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select';

import { SERVE_OPTIONS, serveOption, servesLabel, type Connection, type Serves } from '../_sample/data';
import { channelsStore } from '../_sample/store';

const keyOf = (s: Pick<Serves, 'kind' | 'id'>) => `${s.kind}:${s.id}`;

/**
 * What a connection serves, changed where it is shown: the workflow or agent, then its version (the latest published
 * one, or a pinned one). Changing what it serves goes back to the latest version of the new one.
 */
export function ServesPicker({ connection }: { connection: Connection }) {
  const { serves } = connection;
  const option = serveOption(serves);
  const set = (next: Serves) => {
    channelsStore.setServes(connection.id, next);
    toast.success(`${connection.name} now serves ${servesLabel(next)}`);
  };
  return (
    // A row of the connections table opens its drawer on click; choosing here does not.
    <div className="flex min-w-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()} data-testid={`serves-${connection.id}`}>
      <Select
        value={option ? keyOf(serves) : undefined}
        onValueChange={(v) => {
          const [kind, id] = v.split(':') as [Serves['kind'], string];
          set({ kind, id, version: 'latest' });
        }}
      >
        <SelectTrigger size="sm" className="max-w-40 min-w-0" aria-label={`What ${connection.name} serves`}>
          <SelectValue placeholder="Pick a workflow or agent" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Workflows</SelectLabel>
            {SERVE_OPTIONS.filter((o) => o.kind === 'workflow').map((o) => (
              <SelectItem key={keyOf(o)} value={keyOf(o)}>
                {o.name}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Agents</SelectLabel>
            {SERVE_OPTIONS.filter((o) => o.kind === 'agent').map((o) => (
              <SelectItem key={keyOf(o)} value={keyOf(o)}>
                {o.name}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {option && (
        <Select value={String(serves.version)} onValueChange={(v) => set({ ...serves, version: v === 'latest' ? 'latest' : Number(v) })}>
          <SelectTrigger size="sm" className="w-auto shrink-0" aria-label={`Version ${connection.name} serves`}>
            {/* The short form in the row; the list says how far behind a pinned version is. */}
            <SelectValue>{serves.version === 'latest' ? `Latest · v${option.versions[0]}` : `v${serves.version} pinned`}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="latest">Latest · v{option.versions[0]}</SelectItem>
            <SelectSeparator />
            {option.versions.map((v, i) => (
              <SelectItem key={v} value={String(v)}>
                v{v} pinned{i > 0 ? ` · ${i} behind` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
