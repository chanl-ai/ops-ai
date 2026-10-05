'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { ChevronDown, CircleDashed, Pause, Play, RefreshCw, SearchX, ShieldAlert, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { SensitivityBadge, SourceStatusBadge, SourceTypeIcon, sourceTypeMeta } from '@/components/knowledge/knowledge-meta';
import { PageLayout } from '@/components/page-layout';
import { SourceOverview } from '@/components/sources/source-overview';
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
import { useCancelRun, useConnect, useDeleteSource, usePauseSource, useSource, useSyncSource } from '@/hooks/knowledge-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { count, plural } from '@/lib/format';
import type { SyncOptions } from '@/lib/types/knowledge';

import { SourceHistoryTab } from '../_parts/source-history-tab';
import { SourceItemsTab } from '../_parts/source-items-tab';
import { SourceSettingsTab } from '../_parts/source-settings-tab';

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
  const connect = useConnect();
  const [fullOpen, setFullOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);

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

  return (
    <PageLayout
      icon={<SourceTypeIcon type={s.type} className="size-5 text-muted-foreground" />}
      title={s.name}
      badge={<SourceStatusBadge status={s.status} />}
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>{meta.label}</span>
          {s.connectionLabel && <span className="font-mono text-xs">{s.connectionLabel}</span>}
          <SensitivityBadge level={s.sensitivity} />
          <span>Collection {s.collection}</span>
          <span>Owner {s.owner}</span>
          {s.reprocessPending && <span className="text-amber-700 dark:text-amber-400">Settings changed; reprocess pending</span>}
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
              <p>Syncs stop until it is reconnected. Indexed items stay searchable but will not update.</p>
              <LoadingButton
                size="sm"
                variant="outline"
                className="border-destructive/40 text-foreground"
                isLoading={connect.isPending}
                loadingText="Testing connection…"
                onClick={() => connect.mutate(s.type, { onSuccess: (c) => toast.success(`${c.name} reconnected`, { description: 'Scheduled syncs resume.' }), onError: fail('reconnect') })}
              >
                Reconnect {meta.short}
              </LoadingButton>
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
