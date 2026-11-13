'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { SourceKindIcon } from '@/components/knowledge/knowledge-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { useAttachSources, useSourcesList } from '@/hooks/knowledge-queries';
import { plural } from '@/lib/format';
import { cn } from '@/lib/utils';

/** Pick sources the team already has and attach them to a base; one already feeding it is shown and left unpickable. */
export function AttachSourcesDialog({ open, onOpenChange, kb }: { open: boolean; onOpenChange: (o: boolean) => void; kb: { id: string; name: string } }) {
  const attach = useAttachSources(kb.id);
  const [search, setSearch] = React.useState('');
  const [picked, setPicked] = React.useState<string[]>([]);
  const candidates = useSourcesList({ page: 1, pageSize: 20, search: search || undefined });
  React.useEffect(() => {
    if (open) {
      setPicked([]);
      setSearch('');
    }
  }, [open]);
  const rows = candidates.data?.data ?? [];

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Attach sources"
      description={`Sources ${kb.name} does not read yet. Their items are indexed on the next refresh.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={attach.isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={attach.isPending}
            disabled={!picked.length}
            onClick={async () => {
              try {
                await attach.mutateAsync(picked);
                toast.success(`Attached ${plural(picked.length, 'source')}`, { description: 'Refresh the index to search them.' });
                onOpenChange(false);
              } catch (e) {
                toast.error('Couldn’t attach', { description: (e as Error).message });
              }
            }}
          >
            {picked.length ? `Attach ${plural(picked.length, 'source')}` : 'Attach'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. lending policies" aria-label="Search sources" />
        {candidates.isPending ? (
          <p className="text-sm text-muted-foreground">Loading sources…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{search ? `No source called “${search}”.` : 'No sources yet.'}</p>
        ) : (
          <div className="divide-y rounded-md border">
            {rows.map((s) => {
              const here = s.usedByKbIds.includes(kb.id);
              return (
                <label key={s.id} htmlFor={`att-${s.id}`} className={cn('flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-accent/40', here && 'cursor-default opacity-60', picked.includes(s.id) && 'bg-primary/5')}>
                  <Checkbox id={`att-${s.id}`} disabled={here} checked={here || picked.includes(s.id)} onCheckedChange={(v) => setPicked((p) => (v ? [...p, s.id] : p.filter((x) => x !== s.id)))} />
                  <SourceKindIcon kind={s.kind} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{s.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{here ? 'Already feeds this knowledge base' : `${plural(s.itemsIndexed, 'item')} · ${s.scopeSummary}`}</span>
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </div>
    </DialogShell>
  );
}
