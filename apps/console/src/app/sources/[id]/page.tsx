'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { ChevronDown, CircleDashed, Layers, Pause, Play, RefreshCw, SearchX, ShieldAlert, ShieldCheck, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { SensitivityBadge, SourceStatusBadge, SourceTypeIcon, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { ConnectionChip } from '@/components/integrations/integration-meta';
import { PageLayout } from '@/components/page-layout';
import { SourceOverview } from '@/components/sources/source-overview';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { strategyMeta } from '@/components/sources/ingest-meta';
import { useApproveIngest, useCancelRun, useDeleteSource, usePauseSource, useReprocessSource, useSource, useSyncSource } from '@/hooks/knowledge-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { count, plural } from '@/lib/format';
import type { SyncOptions } from '@/lib/types/knowledge';
import type { IngestStrategy } from '@/lib/types/knowledge-ingest';

import { SourceHistoryTab } from '../_parts/source-history-tab';
import { SourceItemsTab } from '../_parts/source-items-tab';
import { SourceSettingsTab } from '../_parts/source-settings-tab';

/** Lower-cases a label for use inside a sentence, leaving acronyms such as FAQ alone. */
const midSentence = (l: string) => (/^[A-Z]{2}/.test(l) ? l : l.charAt(0).toLowerCase() + l.slice(1));

const TABS = ['overview', 'items', 'history', 'settings'] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { overview: 'Overview', items: 'Items', history: 'Sync history', settings: 'Settings' };

export default function SourcePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'overview');
  const query = useSource(id);
  const sync = useSyncSource();
  const cancel = useCancelRun();
  const pause = usePauseSource();
  const remove = useDeleteSource();
  const reindex = useReprocessSource();
  const approve = useApproveIngest();
  const [fullOpen, setFullOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [approveOpen, setApproveOpen] = React.useState(false);

  if (query.isPending)
    return (
      <PageLayout title="Source" backHref="/sources">
        <PageSkeleton statCards={5} tableRows={5} showToolbar={false} />
      </PageLayout>
    );
  if (query.isError)
    return (
      <PageLayout title="Source" backHref="/sources">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Source not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to sources', href: '/sources' }} />
        ) : (
          <QueryError what="this source" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );

  const s = query.data;
  const meta = sourceTypeMeta(s.type);
  const running = !!s.running;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });
  const startSync = (opts: SyncOptions | undefined, done: string) => sync.mutate({ id: s.id, opts }, { onSuccess: () => toast.success(done), onError: fail('start the sync') });
  const togglePause = () =>
    pause.mutate({ id: s.id, paused: s.status !== 'paused' }, { onSuccess: (x) => toast.success(x.status === 'paused' ? 'Schedule paused' : 'Schedule resumed', { description: s.name }), onError: fail('change the schedule') });
  const tabHref = (t: string, q?: string) => `/sources/${s.id}?tab=${t}${q ? `&${q}` : ''}`;
  const syncBlocked = running || s.status === 'revoked' || s.status === 'draft';
  const stepLabel = (x: string) => (x.startsWith('extract ') ? `extracting ${x.slice(8)} with AI` : midSentence(strategyMeta(x as IngestStrategy).label));
  const waiting = new Set(s.aiStepsWaiting);
  const runsNow = s.ingest.strategies.filter((x) => !waiting.has(x)).map(stepLabel);
  const waits = s.aiStepsWaiting.map(stepLabel);

  return (
    <PageLayout
      icon={<SourceTypeIcon type={s.type} className="size-5 text-muted-foreground" />}
      title={s.name}
      badge={<SourceStatusBadge status={s.status} />}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>{meta.label}</span>
          {s.connection && <ConnectionChip connection={s.connection} />}
          <SensitivityBadge level={s.sensitivity} />
          <span>Collection {s.collection}</span>
          <span>Owner {s.owner}</span>
          {s.reindexNeeded && <span className="text-amber-700 dark:text-amber-400">Re-index needed</span>}
        </span>
      }
      backHref="/sources"
      actions={
        <div className="flex items-center">
          <LoadingButton className="rounded-r-none" isLoading={sync.isPending} disabled={syncBlocked} onClick={() => startSync(undefined, `Syncing ${s.name}`)}>
            <RefreshCw className="size-4" /> {running ? 'Syncing…' : 'Sync now'}
          </LoadingButton>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="rounded-l-none border-l border-primary-foreground/20 px-2" aria-label="More sync actions">
                <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={syncBlocked} onClick={() => setFullOpen(true)}>
                <RefreshCw className="size-4" /> Full resync
              </DropdownMenuItem>
              <DropdownMenuItem disabled={s.status === 'draft' || s.status === 'revoked'} onClick={togglePause}>
                {s.status === 'paused' ? <Play className="size-4" /> : <Pause className="size-4" />} {s.status === 'paused' ? 'Resume schedule' : 'Pause schedule'}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t}>
                {LABEL[t]}
                {t === 'items' && <span className="ml-1 text-muted-foreground tabular-nums">{count(s.itemCount)}</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
    >
      <div className="flex flex-col gap-4">
        {s.status === 'revoked' && (
          <Alert variant="destructive">
            <ShieldAlert className="size-4" />
            <AlertTitle>The {meta.short} connection was revoked</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>Syncs stop until it is reconnected in Integrations. Indexed items stay searchable but will not update.</p>
              {s.connection && (
                <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" asChild>
                  <Link href={`/integrations/${s.connection.id}`}>Open {s.connection.name}</Link>
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}
        {s.status === 'paused' && (
          <Alert>
            <Pause className="size-4" />
            <AlertTitle>Schedule paused</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>Scheduled syncs are skipped. Sync now still runs a one-off sync.</p>
              <Button size="sm" variant="outline" onClick={togglePause}>
                <Play className="size-4" /> Resume schedule
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {s.status === 'draft' && (
          <Alert>
            <CircleDashed className="size-4" />
            <AlertTitle>Draft: finish setting it up</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>This source was saved before setup was complete and does not sync. Check its settings, then sync it once to activate it.</p>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" asChild>
                  <Link href={tabHref('settings')}>Open settings</Link>
                </Button>
                <LoadingButton size="sm" isLoading={sync.isPending} onClick={() => startSync(undefined, `Activated ${s.name}; the first sync has started`)}>
                  Activate and sync
                </LoadingButton>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {s.reindexNeeded && (
          <Alert data-testid="reindex-banner">
            <Layers className="size-4" />
            <AlertTitle>Re-index needed</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>
                The ingestion settings changed since these chunks were built. Search keeps using the old chunks until a re-index rebuilds {plural(s.itemCount, 'item')}.
              </p>
              <p data-testid="reindex-steps">
                Runs now: {runsNow.length ? runsNow.join(', ') : 'structure splitting'}.
                {waits.length > 0 && ` Waits for approval: ${waits.join(', ')}. A later re-index adds ${waits.length === 1 ? 'it' : 'them'} once approved.`}
              </p>
              <LoadingButton
                size="sm"
                isLoading={reindex.isPending}
                disabled={running || s.status === 'revoked'}
                onClick={() => reindex.mutate(s.id, { onSuccess: () => toast.success(`Re-indexing ${s.name}`, { description: 'Runs as a full sync; progress is on the Overview tab.' }), onError: fail('start the re-index') })}
              >
                <RefreshCw className="size-4" /> {running ? 'A sync is running' : 'Re-index now'}
              </LoadingButton>
            </AlertDescription>
          </Alert>
        )}
        {s.ingest.approval.status === 'pending' && (
          <Alert>
            <ShieldCheck className="size-4" />
            <AlertTitle>AI ingestion steps wait for the knowledge owner</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>
                {s.ingest.approval.requestedBy ? `${s.ingest.approval.requestedBy} turned on` : 'This source uses'} {waits.join(' and ')}, which {waits.length === 1 ? 'calls' : 'call'} {s.ingest.model} at ingest. Syncs run without{' '}
                {waits.length === 1 ? 'it' : 'them'} until another knowledge owner approves.
              </p>
              {s.approval && !s.approval.canApprove ? (
                <p className="font-medium" data-testid="self-approval">
                  {s.approval.blockedReason}
                </p>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setApproveOpen(true)}>
                  Review and approve
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}

        {tab === 'overview' && (
          <SourceOverview
            source={s}
            busy={sync.isPending || cancel.isPending}
            onSync={() => startSync(undefined, `Syncing ${s.name}`)}
            onRetryFailed={() => startSync({ retry: true }, `Retrying ${plural(s.itemsFailed, 'failed item')}`)}
            onCancel={() => cancel.mutate(s.id, { onSuccess: () => toast.message('Run cancelled', { description: 'Items already processed stay indexed.' }), onError: fail('cancel the run') })}
            tabHref={tabHref}
          />
        )}
        {tab === 'items' && <SourceItemsTab source={s} onSync={() => startSync(undefined, `Syncing ${s.name}`)} />}
        {tab === 'history' && <SourceHistoryTab source={s} onSync={() => startSync(undefined, `Syncing ${s.name}`)} />}
        {tab === 'settings' && <SourceSettingsTab source={s} onDelete={() => setDeleteOpen(true)} />}
      </div>

      <DialogShell
        open={fullOpen}
        onOpenChange={setFullOpen}
        size="sm"
        title="Run a full resync?"
        description={`A full resync ignores the saved cursor and lists every item again, about ${plural(s.itemsIndexed + s.itemsFailed + s.itemsPending, 'item')}. Items no longer at the source are removed from the index.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setFullOpen(false)}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={sync.isPending}
              onClick={() =>
                sync.mutate(
                  { id: s.id, opts: { full: true } },
                  {
                    onSuccess: () => {
                      toast.success(`Full resync of ${s.name} started`);
                      setFullOpen(false);
                    },
                    onError: fail('start the resync'),
                  },
                )
              }
            >
              Full resync
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">It takes longer than an incremental sync. Agents keep answering from the current index while it runs.</p>
      </DialogShell>

      {s.approval && (
        <ConfirmActionDialog
          open={approveOpen}
          onOpenChange={setApproveOpen}
          title={`Approve AI ingestion for ${s.name}?`}
          consequence={`${waits.join(' and ')} will call ${s.ingest.model} for every item at the next re-index, sending item text through the AI gateway under the ingestion key.`}
          details={[
            { label: 'Requested by', value: s.ingest.approval.requestedBy ?? 'Unknown' },
            { label: 'Documents affected', value: plural(s.approval.items, 'document') },
            { label: 'Model calls', value: `About ${count(s.approval.modelCalls)} per full re-index` },
            { label: 'Estimated cost', value: `About ${s.approval.estimatedCost} per full re-index` },
          ]}
          runsNow
          note="Approving is recorded with your name. Chunks change only when the source is re-indexed."
          confirmLabel="Approve"
          isPending={approve.isPending}
          onConfirm={() => approve.mutateAsync(s.id).then(() => toast.success('AI ingestion steps approved', { description: 'Re-index to build chunks with them.' }))}
        />
      )}

      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="source"
        entityName={s.name}
        requireNameConfirmation={s.readers.length > 0}
        description={`Its sync history and ${plural(s.itemCount, 'item')} are removed.${s.readers.length ? ` Chunks leave ${s.readers.map((k) => k.name).join(', ')}.` : ''}`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(s.id);
            toast.success(`Deleted ${s.name}`);
            router.push('/sources');
          } catch (e) {
            toast.error(`Couldn’t delete ${s.name}`, { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
