'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { ExternalLink, FilePlus2, Loader2, Plug, Plus, RefreshCw, Unlink, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { scheduleLabel, SourceHealthText, SourceKindIcon } from '@/components/knowledge/knowledge-meta';
import { AddPageDialog } from '@/components/knowledge/add-page-dialog';
import { AddDocumentsDialog } from '@/components/shared/add-documents-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { kk, useAddDocuments, useAddPage, useAttachSources, useDetachSource, useSource, useSourcesList, useSyncSource } from '@/hooks/knowledge-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { AddSourceWizard } from '@/components/sources/add-source-wizard';
import { useSticky } from '@/hooks/use-sticky';
import { count, plural, relativeTime } from '@/lib/format';
import type { KbSourceView, KnowledgeBaseDetail, Source, SourceHealth, SyncRun } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Row = KbSourceView & { onRowClick: (r: KbSourceView) => void };

/** Likely questions are "Questions", FAQ drafts are "drafts"; a step waiting for the knowledge owner says so. */
function faqLabel(s: Source) {
  const q = s.ingest.strategies.includes('faq');
  const p = s.ingest.strategies.includes('faq_pairs');
  if (!q && !p) return null;
  return q && p ? 'Questions + drafts' : q ? 'Questions' : 'Drafts';
}

const HEALTH_OPTIONS: { label: string; value: SourceHealth['state'] }[] = [
  { label: 'Healthy', value: 'healthy' },
  { label: 'Failing', value: 'failing' },
  { label: 'Needs reconnect', value: 'needs_reconnect' },
  { label: 'Never synced', value: 'never' },
];

/** A run's progress in words: how many items it has checked of how many it found. */
function runProgress(run: SyncRun) {
  const done = run.counts.checked ?? run.counts.upserted ?? 0;
  return run.counts.total ? `Syncing ${count(done)} of ${count(run.counts.total)}` : 'Syncing';
}

/**
 * The run this tab started, with its progress, read from the source's own detail while it runs; the base is refetched
 * once that run has ended. Runs started elsewhere (the schedule) show through the base's own polling.
 */
function useWatchedRun(kbId: string) {
  const qc = useQueryClient();
  const [id, setId] = React.useState<string | null>(null);
  const watched = useSource(id ?? '', !!id);
  const running = watched.data?.running ?? null;
  React.useEffect(() => {
    if (!id || !watched.data || running) return;
    setId(null);
    void qc.invalidateQueries({ queryKey: kk.kb(kbId) });
  }, [id, watched.data, running, qc, kbId]);
  return { watch: setId, sourceId: id, run: running };
}

/**
 * The sources that feed this knowledge base, each with its kind, schedule, last sync, health as kb-service keeps it,
 * items and FAQ steps. Read from the base's own detail, which lists every attached source.
 */
/** `canBuild` is the knowledge base's own edit flag; adding, attaching, syncing and detaching are hidden from anyone without it. */
export function KbSourcesTab({ kb, canBuild }: { kb: KnowledgeBaseDetail; canBuild: boolean }) {
  const router = useRouter();
  const addDocuments = useAddDocuments(kb.id);
  const addPage = useAddPage(kb.id);
  const [docsOpen, setDocsOpen] = React.useState(false);
  const [pageOpen, setPageOpen] = React.useState(false);
  const attach = useAttachSources(kb.id);
  const detach = useDetachSource(kb.id);
  const [attachOpen, setAttachOpen] = React.useState(false);
  const [attachSearch, setAttachSearch] = React.useState('');
  const candidates = useSourcesList({ page: 1, pageSize: 20, search: attachSearch || undefined });
  const [addOpen, setAddOpen] = React.useState(false);
  const syncSource = useSyncSource();
  const [picked, setPicked] = React.useState<string[]>([]);
  const [detaching, setDetaching] = React.useState<KbSourceView | null>(null);
  const detachingShown = useSticky(detaching);

  const watched = useWatchedRun(kb.id);
  const openSource = React.useCallback((r: KbSourceView) => router.push(`/data/sources/${r.sourceId}`), [router]);
  const syncNow = React.useCallback(
    (r: KbSourceView) =>
      syncSource.mutate(
        { id: r.sourceId },
        {
          onSuccess: () => {
            watched.watch(r.sourceId);
            toast.success(`Syncing ${r.source.name}`);
          },
          onError: (e) => toast.error(`Couldn’t sync ${r.source.name}`, { description: e.message }),
        },
      ),
    [syncSource, watched.watch],
  );
  const rows: Row[] = React.useMemo(() => kb.attached.map((a) => ({ ...a, onRowClick: openSource })), [kb.attached, openSource]);

  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: 'name',
        accessorFn: (r) => r.source.name,
        header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
        cell: ({ row }) => (
          <div className="min-w-48">
            <div className="truncate font-medium">{row.original.source.name}</div>
            <div className="truncate text-xs text-muted-foreground">{row.original.source.scopeSummary}</div>
            {row.original.source.waitingHosts.length > 0 && (
              <div className="truncate text-xs text-warning-text" data-testid="kb-source-host-waiting">
                Waiting for an admin to approve {row.original.source.waitingHosts.map((w) => w.host).join(', ')}
              </div>
            )}
          </div>
        ),
        enableHiding: false,
      },
      {
        id: 'kind',
        accessorFn: (r) => r.source.kindLabel,
        filterFn: facetFilterFn,
        header: 'Kind',
        cell: ({ row }) => (
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            <SourceKindIcon kind={row.original.source.kind} />
            {row.original.source.kindLabel}
          </span>
        ),
      },
      { id: 'schedule', header: 'Schedule', cell: ({ row }) => <span className="whitespace-nowrap">{row.original.source.status === 'paused' ? 'Paused' : scheduleLabel(row.original.source.schedule)}</span> },
      {
        id: 'sync',
        header: 'Last sync',
        cell: ({ row }) =>
          watched.run && watched.sourceId === row.original.sourceId ? (
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-primary" data-testid="kb-source-syncing">
              <Loader2 className="size-3.5 animate-spin" /> {runProgress(watched.run)}
            </span>
          ) : (
            <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.source.lastSyncAt)}</span>
          ),
      },
      {
        id: 'health',
        accessorFn: (r) => r.source.health?.state ?? 'never',
        filterFn: facetFilterFn,
        // Sorted by the last good sync, newest first by default; a source never synced well sorts last.
        sortingFn: (a, b) => (a.original.source.health?.lastGoodSyncAt ?? '').localeCompare(b.original.source.health?.lastGoodSyncAt ?? ''),
        header: ({ column }) => <DataTableColumnHeader column={column} title="Health" />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <SourceHealthText health={row.original.source.health} />
            {row.original.source.health?.lastGoodSyncAt && <span className="text-xs text-muted-foreground">Last good {relativeTime(row.original.source.health.lastGoodSyncAt)}</span>}
          </div>
        ),
      },
      { id: 'items', header: 'Items', cell: ({ row }) => <span className="tabular-nums">{count(row.original.source.itemsIndexed)}</span> },
      {
        id: 'faqs',
        header: 'FAQs',
        cell: ({ row }) => {
          const label = faqLabel(row.original.source);
          if (!label) return <span className="text-muted-foreground">Off</span>;
          return (
            <span className="flex flex-col items-start gap-1">
              <Badge variant="secondary" className="font-normal whitespace-nowrap">
                {label}
              </Badge>
              {row.original.source.ingest.approval.status === 'pending' && <span className="text-xs whitespace-nowrap text-warning-text">Approval pending</span>}
            </span>
          );
        },
      },
      {
        id: 'actions',
        meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
        cell: ({ row }) => (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Open source', icon: ExternalLink, onClick: (r) => openSource(r.original) },
                ...(canBuild
                  ? [
                      { label: 'Sync now', icon: RefreshCw, onClick: (r: { original: KbSourceView }) => syncNow(r.original) },
                      { label: 'Detach', icon: Unlink, variant: 'destructive' as const, onClick: (r: { original: KbSourceView }) => setDetaching(r.original) },
                    ]
                  : []),
              ]}
            />
          </StopRowClick>
        ),
        enableHiding: false,
      },
    ],
    [openSource, syncNow, canBuild, watched.run, watched.sourceId],
  );

  const lastWithPublicLink = kb.sources.length === 1 && kb.access.publicLink.enabled;
  const candidateRows = candidates.data?.data ?? [];
  // Facet values come from the base's own detail, which lists every source it reads, so nothing is fetched to fill them.
  const kindOptions = [...new Set(rows.map((r) => r.source.kindLabel))].map((t) => ({ label: t, value: t }));

  return (
    <div className="flex flex-col gap-3">
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.sourceId}
        searchColumn="name"
        searchPlaceholder="Search sources…"
        hideViewSwitcher
        rowNoun="source"
        initialColumnVisibility={{ kind: true, schedule: true, sync: true, health: true, items: true, faqs: true }}
        initialSorting={[{ id: 'health', desc: true }]}
        filters={[
          { column: 'kind', title: 'Kind', options: kindOptions },
          { column: 'health', title: 'Health', options: HEALTH_OPTIONS },
        ]}
        toolbarExtra={
          canBuild && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setAddOpen(true)} data-testid="kb-add-source">
              <Plus className="size-4" /> Add source
            </Button>
            <Button size="sm" variant="outline" onClick={() => setDocsOpen(true)} data-testid="kb-add-documents">
              <Upload className="size-4" /> Add documents
            </Button>
            <Button size="sm" variant="outline" onClick={() => setPageOpen(true)}>
              <FilePlus2 className="size-4" /> Add page
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setPicked([]);
                setAttachSearch('');
                setAttachOpen(true);
              }}
              data-testid="kb-attach-sources"
            >
              <Plus className="size-4" /> Attach sources
            </Button>
          </div>
          )
        }
        emptyState={
          <EmptyState
            icon={Plug}
            title="No sources yet"
            description={canBuild ? 'Add a website, connect an app, or upload files.' : 'Nobody has added a source here yet.'}
            action={canBuild ? { label: 'Add source', onClick: () => setAddOpen(true) } : undefined}
            secondaryAction={canBuild ? { label: 'Attach existing source', onClick: () => (setPicked([]), setAttachOpen(true)) } : undefined}
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
          const failed = r.run.counts.failed ?? 0;
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
      <AddSourceWizard
        open={addOpen}
        onOpenChange={setAddOpen}
        kb={kb}
        onCreated={(s, approval) => {
          watched.watch(s.id);
          toast.success(`${s.name} created`, {
            description:
              approval.state === 'waiting'
                ? `First sync started. Its questions and FAQ steps wait for the knowledge owner’s approval: ${approval.reason}`
                : approval.state === 'approved'
                  ? 'First sync started, with its questions and FAQ steps approved.'
                  : 'First sync started.',
            action: { label: 'View source', onClick: () => router.push(`/data/sources/${s.id}`) },
          });
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
        <div className="flex flex-col gap-3">
          <Input value={attachSearch} onChange={(e) => setAttachSearch(e.target.value)} placeholder="e.g. lending policies" aria-label="Search sources" />
          {candidates.isPending ? (
            <p className="text-sm text-muted-foreground">Loading sources…</p>
          ) : candidateRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{attachSearch ? `No source called “${attachSearch}”.` : 'No sources yet.'}</p>
          ) : (
            <div className="divide-y rounded-md border">
              {candidateRows.map((s) => {
                // Each row names the bases it already feeds, so one already here is shown and left unpickable.
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

      <DialogShell
        open={!!detaching}
        onOpenChange={(o) => !o && setDetaching(null)}
        size="sm"
        title={lastWithPublicLink ? 'Can’t detach the last source' : `Detach ${detachingShown?.source.name}?`}
        description={
          lastWithPublicLink
            ? 'A knowledge base with a public link must keep at least one source. Turn the link off or attach another source first.'
            : `Its pieces leave ${kb.name}. The source and its items are kept${detachingShown && detachingShown.source.usedByKbIds.length <= 1 ? '; no other knowledge base reads it' : ''}.`
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
        <p className="text-sm text-muted-foreground">Agents citing {kb.name} stop finding this source’s documents.</p>
      </DialogShell>
    </div>
  );
}
