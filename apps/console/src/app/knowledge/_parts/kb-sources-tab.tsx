'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ExternalLink, FilePlus2, Plug, Plus, Unlink, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { RunStatusBadge, SensitivityBadge, SourceTypeIcon, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { AddPageDialog } from '@/components/knowledge/add-page-dialog';
import { AddDocumentsDialog } from '@/components/shared/add-documents-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useIntegrationOptions } from '@/hooks/integration-queries';
import { useAddDocuments, useAddPage, useAttachSources, useCreateSource, useDetachSource, useSourcesList, useSyncSource } from '@/hooks/knowledge-queries';
import { NewSourceDialog } from '@/components/sources/new-source-dialog';
import { useSticky } from '@/hooks/use-sticky';
import { count, plural, relativeTime } from '@/lib/format';
import type { KbSourceView, KnowledgeBaseDetail } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Row = KbSourceView & { onRowClick: (r: KbSourceView) => void };
const ALL = { page: 1, pageSize: 100 };

/**
 * Which sources feed this knowledge base, and what each one contributes. Add documents is the main way in (c-159):
 * new files go to Files first, then into the base's documents source with any picked from Files, synced at once.
 */
export function KbSourcesTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const router = useRouter();
  const addDocuments = useAddDocuments(kb.id);
  const addPage = useAddPage(kb.id);
  const [docsOpen, setDocsOpen] = React.useState(false);
  const [pageOpen, setPageOpen] = React.useState(false);
  const allSources = useSourcesList(ALL);
  const attach = useAttachSources(kb.id);
  const detach = useDetachSource(kb.id);
  const [attachOpen, setAttachOpen] = React.useState(false);
  const [addOpen, setAddOpen] = React.useState(false);
  const connections = useIntegrationOptions(addOpen);
  const create = useCreateSource();
  const syncSource = useSyncSource();
  const [picked, setPicked] = React.useState<string[]>([]);
  const [detaching, setDetaching] = React.useState<KbSourceView | null>(null);
  const detachingShown = useSticky(detaching);

  const openSource = React.useCallback((r: KbSourceView) => router.push(`/integrations/sources/${r.sourceId}`), [router]);
  const unattached = (allSources.data?.data ?? []).filter((s) => !kb.sources.some((l) => l.sourceId === s.id));
  const rows: Row[] = React.useMemo(() => kb.attached.map((a) => ({ ...a, onRowClick: openSource })), [kb.attached, openSource]);

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: 'name',
        accessorFn: (r) => r.source.name,
        header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
        cell: ({ row }) => (
          <div className="flex min-w-48 items-center gap-2">
            <SourceTypeIcon type={row.original.source.type} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.source.name}</div>
              <div className="truncate text-xs text-muted-foreground">
                {sourceTypeMeta(row.original.source.type).label} · {row.original.source.collection}
              </div>
            </div>
          </div>
        ),
        enableHiding: false,
      },
      { id: 'items', accessorFn: (r) => r.itemsContributed, header: ({ column }) => <DataTableColumnHeader column={column} title="Items contributed" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.itemsContributed)}</span> },
      {
        id: 'filter',
        header: () => <span className="text-xs">Filter</span>,
        cell: ({ row }) =>
          row.original.rules.length ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="cursor-default font-normal">
                  {plural(row.original.rules.length, 'rule')}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                {row.original.rules.map((r) => (
                  <div key={r.id} className="font-mono text-xs">
                    {r.kind} {r.field} {r.value}
                  </div>
                ))}
              </TooltipContent>
            </Tooltip>
          ) : (
            <Badge variant="secondary" className="font-normal">
              Everything
            </Badge>
          ),
      },
      { id: 'sensitivity', header: () => <span className="text-xs">Sensitivity</span>, cell: ({ row }) => <SensitivityBadge level={row.original.source.sensitivity} /> },
      { id: 'sync', accessorFn: (r) => r.source.lastSyncAt ?? '', header: ({ column }) => <DataTableColumnHeader column={column} title="Last sync" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.source.lastSyncAt)}</span> },
      { id: 'status', header: () => <span className="text-xs">Status</span>, cell: ({ row }) => <RunStatusBadge status={row.original.source.status === 'revoked' ? 'failed' : row.original.source.lastRunStatus} /> },
      {
        id: 'actions',
        meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
        cell: ({ row }) => (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Open source', icon: ExternalLink, onClick: (r) => openSource(r.original) },
                { label: 'Detach', icon: Unlink, variant: 'destructive', onClick: (r) => setDetaching(r.original) },
              ]}
            />
          </StopRowClick>
        ),
        enableHiding: false,
      },
    ],
    [openSource],
  );

  const lastWithPublicLink = kb.sources.length === 1 && kb.access.publicLink.enabled;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">Changing a source’s parsing or chunking reprocesses its items once; every knowledge base picks up the new chunks on its next refresh.</p>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.sourceId}
        searchColumn="name"
        searchPlaceholder="Search attached sources…"
        hideViewSwitcher
        toolbarExtra={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setDocsOpen(true)} data-testid="kb-add-documents">
              <Upload className="size-4" /> Add documents
            </Button>
            <Button size="sm" variant="outline" onClick={() => setPageOpen(true)}>
              <FilePlus2 className="size-4" /> Add page
            </Button>
            <Button size="sm" variant="outline" onClick={() => setAddOpen(true)} data-testid="kb-add-source">
              <Plus className="size-4" /> Add source
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setPicked([]);
                setAttachOpen(true);
              }}
              data-testid="kb-attach-sources"
            >
              <Plus className="size-4" /> Attach sources
            </Button>
          </div>
        }
        emptyState={
          <EmptyState
            icon={Plug}
            title="Add documents"
            description="Upload files or pick ones already in Files; they are indexed straight away. A source that fetches from a system can be added or attached too."
            action={{ label: 'Add documents', onClick: () => setDocsOpen(true) }}
            secondaryAction={{ label: 'Attach existing source', onClick: () => (setPicked([]), setAttachOpen(true)) }}
          />
        }
      />

      <AddDocumentsDialog
        open={docsOpen}
        onOpenChange={setDocsOpen}
        purpose="knowledge_source"
        description={`Uploads are stored in Files first. Each document is indexed into ${kb.name} once you add it.`}
        isPending={addDocuments.isPending}
        onSubmit={async (fileIds) => {
          const r = await addDocuments.mutateAsync(fileIds);
          const failed = r.run.counts.failed;
          toast.success(`Added ${plural(r.files.length, 'document')} to ${kb.name}`, { description: failed ? `${plural(failed, 'document')} could not be read; open the source to see why.` : 'Indexed; agents can cite them now.' });
          setDocsOpen(false);
        }}
      />
      <AddPageDialog
        open={pageOpen}
        onOpenChange={setPageOpen}
        saving={addPage.isPending}
        onSubmit={(input) => addPage.mutateAsync(input).then((d) => toast.success(`Added ${d.title}`, { description: d.status === 'indexed' ? 'Indexed; agents can cite it now.' : d.error }))}
      />
      <NewSourceDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        connections={connections.data ?? []}
        existingNames={(allSources.data?.data ?? []).map((x) => x.name)}
        isPending={create.isPending}
        onSubmit={(input) => create.mutateAsync({ input, sync: false, kbIds: [kb.id] })}
        onSync={(id) => syncSource.mutateAsync({ id })}
        onCreated={(s, synced) => {
          toast.success(synced ? `Added ${s.name} to ${kb.name} and syncing` : `Added ${s.name} to ${kb.name} as a draft`, { description: synced ? 'Its files are being read; the index builds from them.' : 'Set its scope and schedule, then sync it; the index builds from what it fetches.' });
          router.push(`/integrations/sources/${s.id}?tab=${synced ? 'items' : 'settings'}`);
        }}
      />
      <DialogShell
        open={attachOpen}
        onOpenChange={setAttachOpen}
        size="md"
        title="Attach sources"
        description={`Sources ${kb.name} does not read yet. Their items are indexed on the next refresh.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setAttachOpen(false)} disabled={attach.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={attach.isPending}
              disabled={!picked.length}
              onClick={async () => {
                try {
                  await attach.mutateAsync(picked);
                  toast.success(`Attached ${plural(picked.length, 'source')}`, { description: 'Refresh the index to search them.' });
                  setAttachOpen(false);
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
        {unattached.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Every source is already attached.{' '}
            <Link href="/integrations" className="underline underline-offset-4">
              Add a new source
            </Link>
            .
          </p>
        ) : (
          <div className="divide-y rounded-md border">
            {unattached.map((s) => (
              <label key={s.id} htmlFor={`att-${s.id}`} className={cn('flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-accent/40', picked.includes(s.id) && 'bg-primary/5')}>
                <Checkbox id={`att-${s.id}`} checked={picked.includes(s.id)} onCheckedChange={(v) => setPicked((p) => (v ? [...p, s.id] : p.filter((x) => x !== s.id)))} />
                <SourceTypeIcon type={s.type} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{s.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {plural(s.itemsIndexed, 'item')} · {s.collection}
                  </span>
                </span>
                {kb.collections.length > 0 && !kb.collections.includes(s.collection) && (
                  <Badge variant="outline" className="font-normal text-warning-text">
                    Outside its collections
                  </Badge>
                )}
              </label>
            ))}
          </div>
        )}
      </DialogShell>

      <DialogShell
        open={!!detaching}
        onOpenChange={(o) => !o && setDetaching(null)}
        size="sm"
        title={lastWithPublicLink ? 'Can’t detach the last source' : `Detach ${detachingShown?.source.name}?`}
        description={
          lastWithPublicLink
            ? 'A knowledge base with a public link must keep at least one source. Turn the link off or attach another source first.'
            : `Chunks from this source leave ${kb.name} on the next refresh. The source and its items are kept${detachingShown && detachingShown.source.usedByKbIds.length <= 1 ? '; no other knowledge base reads it' : ''}.`
        }
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setDetaching(null)} disabled={detach.isPending}>
              {lastWithPublicLink ? 'Close' : 'Cancel'}
            </Button>
            {!lastWithPublicLink && (
              <LoadingButton
                variant="destructive"
                isLoading={detach.isPending}
                onClick={async () => {
                  const d = detaching!;
                  try {
                    await detach.mutateAsync(d.sourceId);
                    toast.success(`Detached ${d.source.name}`);
                    setDetaching(null);
                  } catch (e) {
                    toast.error('Couldn’t detach', { description: (e as Error).message });
                  }
                }}
              >
                Detach
              </LoadingButton>
            )}
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">Agents citing {kb.name} stop finding this source’s documents once the index refreshes.</p>
      </DialogShell>
    </div>
  );
}
