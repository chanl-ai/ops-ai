'use client';

import * as React from 'react';
import { Search, UserCheck, Users } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { AccessBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import type { GrantableTool } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

/**
 * Pick which operations an agent may call, grouped by the module they belong to. Workflows exposed
 * to agents are their own group: calling one starts a run, which keeps the workflow's review gates.
 */
export function GrantToolsDialog({
  open,
  onOpenChange,
  tools,
  loading,
  granted,
  stale,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tools: GrantableTool[];
  loading: boolean;
  granted: string[];
  /** Granted ids the catalogue no longer offers; listed apart so they can be removed, and dropped on save anyway. */
  stale: string[];
  onSubmit: (toolIds: string[]) => Promise<unknown>;
  isPending: boolean;
}) {
  const [selected, setSelected] = React.useState<Set<string>>(new Set(granted));
  const [search, setSearch] = React.useState('');
  React.useEffect(() => {
    if (open) {
      setSelected(new Set(granted));
      setSearch('');
    }
  }, [open, granted]);

  const visible = tools.filter((t) => !search || `${t.name} ${t.server} ${t.description}`.toLowerCase().includes(search.toLowerCase()));
  const groups = [...new Set(visible.map((t) => t.server))];
  const toggle = (id: string, on: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      if (on) n.add(id);
      else n.delete(id);
      return n;
    });

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Grant tools"
      description="The agent can call only the operations ticked here, and only while its workflow holds an approval for the module."
      headerExtra={
        <div className="relative pt-2">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 mt-1 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search operations or modules…" className="pl-8" aria-label="Search tools" />
        </div>
      }
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground tabular-nums">{selected.size} selected</span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={isPending}
              loadingText="Saving…"
              onClick={async () => {
                await onSubmit([...selected]);
                onOpenChange(false);
              }}
            >
              Save grants
            </LoadingButton>
          </div>
        </div>
      }
    >
      {loading ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {stale.some((id) => selected.has(id)) && (
            <div className="flex flex-col gap-1" data-testid="stale-grants">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">No longer offered</p>
              <ul className="flex flex-col divide-y rounded-lg border border-warning/40">
                {stale
                  .filter((id) => selected.has(id))
                  .map((id) => (
                    <li key={id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                      <span className="min-w-0">
                        <code className="font-mono text-sm">{id}</code>
                        <span className="block text-xs text-muted-foreground">Unpublished, hidden or removed from its module. Saving drops it.</span>
                      </span>
                      <Button variant="outline" size="sm" onClick={() => toggle(id, false)} aria-label={`Remove ${id}`}>
                        Remove
                      </Button>
                    </li>
                  ))}
              </ul>
            </div>
          )}
          {visible.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No operations match “{search}”.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map((g) => (
            <div key={g} className="flex flex-col gap-1">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{g}</p>
              <ul className="flex flex-col divide-y rounded-lg border">
                {visible
                  .filter((t) => t.server === g)
                  .map((t) => (
                    <li key={t.id}>
                      <label htmlFor={`grant-${t.id}`} className="flex cursor-pointer items-start gap-3 px-3 py-2.5 hover:bg-muted/40">
                        <Checkbox id={`grant-${t.id}`} checked={selected.has(t.id)} onCheckedChange={(v) => toggle(t.id, !!v)} className="mt-0.5" />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <code className="font-mono text-sm">{t.name}</code>
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">{t.description}</span>
                          {Object.keys(t.inputSchema.properties ?? {}).length > 0 && (
                            <span className="block truncate font-mono text-[11px] text-muted-foreground">
                              {Object.keys(t.inputSchema.properties ?? {})
                                .map((f) => (t.inputSchema.required?.includes(f) ? f : `${f}?`))
                                .join(', ')}
                            </span>
                          )}
                        </span>
                        <span className="flex shrink-0 flex-col items-end gap-1">
                          <AccessBadge access={t.access} />
                          {(t.approval || t.requiresApproval) && (
                            <span className="flex items-center gap-1 text-[11px] text-warning-text">
                              <UserCheck className="size-3" /> {t.approval ?? 'Waits for approval'}
                            </span>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
            </div>
          )}
        </div>
      )}
    </DialogShell>
  );
}
