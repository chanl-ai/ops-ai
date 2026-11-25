'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { CircleAlert, CircleCheck, ExternalLink, FolderInput, FolderOpen, FolderSearch, Loader2, Pencil, Plug, RefreshCw, Unplug } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { WatchFolderDialog } from '@/components/files/watch-folder-dialog';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { StopRowClick } from '@/components/shared/form-field';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { type Watch, useCheckWatch, useDeleteWatch, useWatches } from '@/hooks/file-queries';
import { useCan } from '@/hooks/me-queries';
import { useSystemCard } from '@/hooks/systems-queries';
import { useListParams } from '@/hooks/use-list-params';
import { appPageHref } from '@/lib/app-links';
import { bytes, plural, relativeTime } from '@/lib/format';

type Row = Watch;

/** The guide's page on watching a folder, which says what to do about each failed file. */
const WATCH_GUIDE = 'https://opsai.chanl.ai/docs/guide/watch-a-folder';

/** An app's id as a name when its card is not there: its last word, capitalised. */
const plainName = (plugin: string) => (plugin.split('.').pop() ?? plugin).replace(/^\w/, (c) => c.toUpperCase());

/** The app's name from its card; the card is cached, so a list of watches of one app asks once. */
function AppName({ plugin }: { plugin: string }) {
  const card = useSystemCard(`plugin:${plugin}`);
  if (card.isPending) return <span className="inline-block h-3 w-16 animate-pulse rounded bg-muted align-middle" aria-hidden />;
  return <>{card.data?.name ?? plainName(plugin)}</>;
}

/**
 * The folders a watch was set up with, by the names the picker showed: the first two and how many more. A watch saved
 * without names (from the SDK or CLI) has none, so its picked ids are counted per list.
 */
function scopeSummary(folders: Watch['folders'], values: Watch['values']) {
  if (!folders.length) {
    const parts = Object.entries(values).flatMap(([k, v]) => (Array.isArray(v) && v.length ? [`${k.replace(/_/g, ' ')}: ${v.length}`] : []));
    return parts.join(' · ') || 'Whole source';
  }
  const shown = folders.slice(0, 2).map((f) => f.name).join(', ');
  return folders.length > 2 ? `${shown} and ${folders.length - 2} more` : shown;
}

/** What a refused check's code means for a person: the alert's words, and the fix on the app's page when there is one. */
function refusal(code: string | undefined): { title: string; fallback: string; next: string; action?: string } {
  switch (code) {
    case 'unreachable':
      return { title: 'could not be reached', fallback: 'Apps did not answer.', next: 'the next check tries again by itself.' };
    case 'not_installed':
    case 'app_off':
      return { title: 'is off for this team', fallback: 'The app is not turned on.', next: 'the next check after it is on takes everything since.', action: 'Turn on' };
    case 'needs_reconnect':
      return { title: 'refused the sign-in', fallback: 'No check could sign in.', next: 'the next check after reconnecting takes everything since.', action: 'Reconnect' };
    default:
      return { title: 'refused the check', fallback: 'No check could read the folder.', next: 'the next check lists the same changes again.' };
  }
}

/** Why a check stopped partial, by its code: what was left and what the next check does about it. */
function partialReason(code: string | undefined, stopped: string | undefined): string {
  switch (code) {
    case 'fetch_failed':
      return 'some files could not be fetched; the next check tries them again';
    case 'rate_limited':
      return "stopped at the app's rate limit; the next check continues";
    case 'continues':
      return 'the folder is long; the next check lists on from here';
    case 'list_failed':
      return 'the listing stopped part way; the next check lists the same changes again';
    default:
      return stopped || 'the next check continues from here';
  }
}

/** `stacked` is the copy under the name on a phone, where the Last check column is hidden; it carries no test ids so each is found once. */
function LastCheck({ w, stacked }: { w: Watch; stacked?: boolean }) {
  const id = (name: string) => (stacked ? undefined : `${name}-${w.id}`);
  if (w.checking)
    return (
      <span className="inline-flex items-center gap-1.5 text-sm" data-testid={id('watch-checking')}>
        <Loader2 className="size-4 animate-spin text-muted-foreground" /> Checking…
      </span>
    );
  const c = w.lastCheck;
  if (!c || !w.lastCheckAt) return <span className="text-sm text-muted-foreground">Not checked yet</span>;
  const at = relativeTime(w.lastCheckAt);
  if (c.status === 'refused' || c.status === 'failed')
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-destructive-text" data-testid={id('watch-last-check')} data-status={c.status}>
        <CircleAlert className="size-4" /> {c.status === 'refused' ? 'Refused' : 'Failed'} {at}
      </span>
    );
  if (c.status === 'partial')
    return (
      <span className="inline-flex items-start gap-1.5 text-sm text-warning-text" data-testid={id('watch-last-check')} data-status="partial">
        <CircleAlert className="mt-0.5 size-4 shrink-0" />
        <span>
          Partial {at}
          {c.brought ? ` · ${plural(c.brought, 'file')} brought in` : ''} · {partialReason(c.code, c.stopped)}
        </span>
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-sm" data-testid={id('watch-last-check')} data-status={c.status}>
      <CircleCheck className="size-4 text-success" /> {at} · {c.brought ? `${plural(c.brought, 'file')} brought in` : 'nothing new'}
      {c.removed ? ` · ${c.removed} removed` : ''}
    </span>
  );
}

type Failure = NonNullable<NonNullable<Watch['lastCheck']>['failures']>[number];

/** Too large to bring in: said by the check's code, or by the reason on outcomes kept before codes were. */
function tooLarge(f: Failure | undefined) {
  return f?.code === 'too_large' || (!f?.code && /larger than|too large|too big/i.test(f?.reason ?? ''));
}

/** Why the file failed, in the check's words: its size limit, or that it could not be fetched. */
function why(f: Failure) {
  if (f.code === 'too_large') return f.reason ?? 'Too large to bring in';
  if (f.code === 'fetch_failed') return 'Could not be fetched';
  return f.reason ?? '';
}

/** What a person does about a failed file, from the code the check gave. */
function nextStep(f: Failure | undefined) {
  return tooLarge(f)
    ? 'Split it or make it smaller, or upload it to Files directly. It stays out until then.'
    : 'The next checks try it again; if it keeps failing, change the file in the app or upload it directly.';
}

/**
 * The failed files of the last check, under the count in the In Files cell: the first one, why, and what to do. At phone
 * width that column is a few characters wide, so the same text sits under the folder's name instead (`stacked`).
 */
function Failures({ w, stacked }: { w: Watch; stacked?: boolean }) {
  const c = w.lastCheck;
  if (!c || !c.failed) return null;
  const first = c.failures?.[0];
  return (
    <span className={`flex min-w-0 max-w-80 flex-col gap-0.5 whitespace-normal break-words text-xs text-destructive-text ${stacked ? 'mt-1 sm:hidden' : 'max-sm:hidden'}`} data-testid={stacked ? `watch-failed-stacked-${w.id}` : `watch-failed-${w.id}`}>
      <span>
        {c.failed} failed{first ? `: ${first.path ?? 'a file'}${first.size ? `, ${bytes(first.size)}` : ''}${why(first) ? `. ${why(first)}` : ''}` : ''}
      </span>
      <span className="text-muted-foreground">
        {nextStep(first)}{' '}
        <a href={`${WATCH_GUIDE}#failed-files`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline underline-offset-2" data-testid={stacked ? undefined : `watch-failed-help-${w.id}`}>
          What to do <ExternalLink className="size-3" />
        </a>
      </span>
    </span>
  );
}

/**
 * One alert for an app whose checks were refused. It waits for the app's card: while the name loads it has no text, so an
 * alert drawn then reads "Checks stopped:  refused the sign-in" with a gap where the name goes. A card that fails to load
 * settles the query, and the alert falls back to the id's last word.
 */
function RefusedAlert({ w, canManage }: { w: Watch; canManage: boolean }) {
  const card = useSystemCard(`plugin:${w.plugin}`);
  if (card.isPending) return null;
  const why = refusal(w.lastCheck?.code);
  return (
    <Alert data-testid="watch-refused" data-code={w.lastCheck?.code || undefined}>
      <Plug className="size-4" />
      <AlertTitle>
        Checks stopped: <AppName plugin={w.plugin} /> {why.title}
      </AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-2">
        <span>
          {w.lastCheck?.stopped || why.fallback} Nothing was lost; {why.next}
          {canManage || !why.action ? '' : ' Ask a builder to fix it on the app’s page.'}
        </span>
        {canManage && why.action && (
          <Button asChild variant="outline" size="sm">
            <Link href={appPageHref(`plugin:${w.plugin}`)} data-testid="watch-reconnect">
              <Plug className="size-4" /> {why.action}
            </Link>
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

function columns(onCheck: ((w: Watch) => void) | undefined, onChange: (w: Watch) => void, onStop: (w: Watch) => void): ColumnDef<Row>[] {
  const base: ColumnDef<Row>[] = [
    {
      id: 'name',
      accessorFn: (w) => w.name,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Watched folder" />,
      meta: { kind: 'name', wrap: true },
      cell: ({ row }) => (
        <div className="flex min-w-0 max-w-96 flex-col" data-testid={`watch-row-${row.original.id}`}>
          <span className="truncate font-medium">{row.original.name}</span>
          <span className="truncate text-xs text-muted-foreground">
            <AppName plugin={row.original.plugin} /> · {scopeSummary(row.original.folders, row.original.values)}
          </span>
          <span className="mt-1 sm:hidden">
            <LastCheck w={row.original} stacked />
          </span>
          <span className="mt-1 text-xs tabular-nums text-muted-foreground sm:hidden">{plural(row.original.filesInFiles, 'file')} in Files</span>
          <Failures w={row.original} stacked />
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'files',
      header: 'In Files',
      meta: { className: 'max-sm:hidden min-w-64' },
      cell: ({ row }) => (
        <div className="flex flex-col gap-1">
          <span className="text-sm tabular-nums" data-testid={`watch-files-${row.original.id}`}>
            {plural(row.original.filesInFiles, 'file')}
          </span>
          <Failures w={row.original} />
        </div>
      ),
    },
    { id: 'lastCheck', header: 'Last check', meta: { className: 'max-sm:hidden' }, cell: ({ row }) => <LastCheck w={row.original} /> },
  ];
  if (!onCheck) return base;
  return [
    ...base,
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Check now', icon: RefreshCw, onClick: (r) => onCheck(r.original), disabledReason: row.original.checking ? 'A check of this folder is running' : undefined },
              { label: 'Change folders', icon: Pencil, onClick: (r) => onChange(r.original) },
              { label: 'Stop watching', icon: Unplug, variant: 'destructive', onClick: (r) => onStop(r.original), disabledReason: row.original.inUse ? 'A workflow starts from this folder; remove it there first' : undefined },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

/** Files › Watched folders: the folders of an app whose files arrive in Files, and what each check found. */
export default function WatchedFoldersPage() {
  const list = useListParams('name');
  const query = useWatches(list.params);
  const canManage = useCan('watches', 'manage') === true;
  const check = useCheckWatch();
  const del = useDeleteWatch();
  const [dialog, setDialog] = React.useState<{ watch?: Watch } | null>(null);
  const [stopping, setStopping] = React.useState<Watch | null>(null);
  const [resetKey, setResetKey] = React.useState(0);

  const askCheck = React.useCallback(
    (w: Watch) =>
      check.mutate(w.id, {
        onSuccess: () => toast.success(`Checking ${w.name}`),
        onError: (e) => ((e as { code?: string }).code === 'already_checking' ? toast.info('A check of this folder is already running') : toast.error(`Couldn’t start the check: ${e.message}`)),
      }),
    [check],
  );
  const cols = React.useMemo(() => columns(canManage ? askCheck : undefined, (w) => setDialog({ watch: w }), setStopping), [canManage, askCheck]);
  const rows = query.data?.data ?? [];
  // One alert per app and reason a check was refused, saying that reason and, where a person can fix it, the way.
  const refused = Object.values(
    Object.fromEntries(rows.filter((w) => !w.checking && w.lastCheck?.status === 'refused').map((w) => [`${w.plugin}:${w.lastCheck?.code ?? ''}`, w])),
  );

  return (
    <PageLayout
      switcher
      icon={FolderOpen}
      title="Files"
      description="Folders of your apps whose files arrive here, one entry per file and a version per change."
      actions={
        canManage ? (
          <Button onClick={() => setDialog({})} data-testid="watch-add">
            <FolderInput className="size-4" /> Watch a folder
          </Button>
        ) : undefined
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={5} />
      ) : query.isError && !query.data ? (
        <QueryError what="watched folders" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : (
        <div className="flex flex-col gap-4">
          {refused.map((w) => (
            <RefusedAlert key={`${w.plugin}:${w.lastCheck?.code ?? ''}`} w={w} canManage={canManage} />
          ))}
          <DataTableWithViews
            columns={cols}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="name"
            searchPlaceholder="Search watched folders…"
            onColumnFiltersChange={list.onColumnFiltersChange}
            filterResetKey={resetKey}
            serverPagination={serverPagination(list, query)}
            hideViewSwitcher
            emptyState={
              <ListEmpty
                icon={FolderSearch}
                noun="watched folders"
                filtered={list.isFiltered}
                onClear={() => setResetKey((k) => k + 1)}
                description="Watch a SharePoint folder and its files arrive here, one entry per file and a version per change."
                createLabel={canManage ? 'Watch a folder' : undefined}
                onCreate={() => setDialog({})}
              />
            }
          />
        </div>
      )}
      <WatchFolderDialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} watch={dialog?.watch} />
      <AlertDialog open={!!stopping} onOpenChange={(o) => !o && !del.isPending && setStopping(null)}>
        <AlertDialogContent data-testid="watch-stop-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle className="break-words">Stop watching {stopping?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Files stops checking this folder, so files that change in {stopping ? <AppName plugin={stopping.plugin} /> : 'the app'} are no longer brought in. The {stopping ? plural(stopping.filesInFiles, 'file') : 'files'} already in Files stay there, with their versions and their retention. To start again, watch the folder again; it is read whole.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={del.isPending}>Keep watching</AlertDialogCancel>
            <AlertDialogAction
              disabled={del.isPending}
              data-testid="watch-stop-confirm"
              onClick={async (e) => {
                e.preventDefault();
                if (!stopping) return;
                try {
                  await del.mutateAsync(stopping.id);
                  toast.success(`Stopped watching ${stopping.name}`, { description: 'Its files stay in Files.' });
                  setStopping(null);
                } catch (err) {
                  toast.error(`Couldn’t stop watching it: ${(err as Error).message}`);
                }
              }}
            >
              {del.isPending ? 'Stopping…' : 'Stop watching'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageLayout>
  );
}
