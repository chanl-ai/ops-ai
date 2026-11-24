'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { CircleAlert, CircleCheck, FolderInput, FolderOpen, FolderSearch, Loader2, Pencil, Plug, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { FilesTabs } from '@/components/files/files-tabs';
import { WatchFolderDialog } from '@/components/files/watch-folder-dialog';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { StopRowClick } from '@/components/shared/form-field';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { type Watch, useCheckWatch, useDeleteWatch, useWatches } from '@/hooks/file-queries';
import { useCan } from '@/hooks/me-queries';
import { useSystemCard } from '@/hooks/systems-queries';
import { useListParams } from '@/hooks/use-list-params';
import { appPageHref } from '@/lib/app-links';
import { bytes, plural, relativeTime } from '@/lib/format';

type Row = Watch;

/** The app's name from its card; the card is cached, so a list of watches of one app asks once. */
function AppName({ plugin }: { plugin: string }) {
  const card = useSystemCard(`plugin:${plugin}`);
  return <>{card.data?.name ?? plugin.split('.').pop()}</>;
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

function LastCheck({ w }: { w: Watch }) {
  if (w.checking)
    return (
      <span className="inline-flex items-center gap-1.5 text-sm" data-testid={`watch-checking-${w.id}`}>
        <Loader2 className="size-4 animate-spin text-muted-foreground" /> Checking…
      </span>
    );
  const c = w.lastCheck;
  if (!c || !w.lastCheckAt) return <span className="text-sm text-muted-foreground">Not checked yet</span>;
  const at = relativeTime(w.lastCheckAt);
  if (c.status === 'refused' || c.status === 'failed')
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-destructive-text">
        <CircleAlert className="size-4" /> {c.status === 'refused' ? 'Refused' : 'Failed'} {at}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      <CircleCheck className="size-4 text-success" /> {at} · {c.brought ? `${plural(c.brought, 'file')} brought in` : 'nothing new'}
      {c.removed ? ` · ${c.removed} removed` : ''}
    </span>
  );
}

function Failures({ w }: { w: Watch }) {
  const c = w.lastCheck;
  if (!c || !c.failed) return <span className="text-xs text-muted-foreground">None</span>;
  const first = c.failures?.[0];
  return (
    <span className="text-sm" data-testid={`watch-failed-${w.id}`}>
      {c.failed} failed{first ? `: ${first.path ?? 'a file'}${first.size ? `, ${bytes(first.size)}` : ''}${first.reason ? ` (${first.reason})` : ''}` : ''}
    </span>
  );
}

function columns(onCheck: ((w: Watch) => void) | undefined, onChange: (w: Watch) => void, onDelete: (w: Watch) => void): ColumnDef<Row>[] {
  const base: ColumnDef<Row>[] = [
    {
      id: 'name',
      accessorFn: (w) => w.name,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Watched folder" />,
      meta: { kind: 'name' },
      cell: ({ row }) => (
        <div className="flex min-w-0 max-w-96 flex-col" data-testid={`watch-row-${row.original.id}`}>
          <span className="truncate font-medium">{row.original.name}</span>
          <span className="truncate text-xs text-muted-foreground">
            <AppName plugin={row.original.plugin} /> · {scopeSummary(row.original.folders, row.original.values)}
          </span>
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'files',
      header: 'In Files',
      cell: ({ row }) => (
        <span className="text-sm tabular-nums" data-testid={`watch-files-${row.original.id}`}>
          {plural(row.original.filesInFiles, 'file')}
        </span>
      ),
    },
    { id: 'lastCheck', header: 'Last check', cell: ({ row }) => <LastCheck w={row.original} /> },
    { id: 'failures', header: 'Needs attention', cell: ({ row }) => <Failures w={row.original} /> },
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
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => onDelete(r.original), disabledReason: row.original.inUse ? 'A workflow’s Files changed trigger uses this folder' : undefined },
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
  const [deleting, setDeleting] = React.useState<Watch | null>(null);
  const [resetKey, setResetKey] = React.useState(0);

  const askCheck = React.useCallback(
    (w: Watch) =>
      check.mutate(w.id, {
        onSuccess: () => toast.success(`Checking ${w.name}`),
        onError: (e) => ((e as { code?: string }).code === 'already_checking' ? toast.info('A check of this folder is already running') : toast.error(`Couldn’t start the check: ${e.message}`)),
      }),
    [check],
  );
  const cols = React.useMemo(() => columns(canManage ? askCheck : undefined, (w) => setDialog({ watch: w }), setDeleting), [canManage, askCheck]);
  const rows = query.data?.data ?? [];
  // One alert per app whose sign-in was refused, with the way to fix it on the app's page.
  const refused = Object.values(Object.fromEntries(rows.filter((w) => !w.checking && w.lastCheck?.status === 'refused').map((w) => [w.plugin, w])));

  return (
    <PageLayout
      switcher
      icon={FolderOpen}
      title="Files"
      description="Folders of your apps whose files arrive here, one entry per file and a version per change."
      tabs={<FilesTabs />}
      actions={
        canManage ? (
          <Button onClick={() => setDialog({})} data-testid="watch-add">
            <FolderInput className="size-4" /> Watch folder
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
            <Alert key={w.plugin} data-testid="watch-refused">
              <Plug className="size-4" />
              <AlertTitle>
                Checks stopped: <AppName plugin={w.plugin} /> refused the sign-in
              </AlertTitle>
              <AlertDescription className="flex flex-col items-start gap-2">
                <span>
                  {w.lastCheck?.stopped || 'No check could reach it.'} Nothing was lost; the next check after reconnecting takes everything since.
                  {canManage ? '' : ' Ask a builder to reconnect.'}
                </span>
                {canManage && (
                  <Button asChild variant="outline" size="sm">
                    <Link href={appPageHref(`plugin:${w.plugin}`)} data-testid="watch-reconnect">
                      <Plug className="size-4" /> Reconnect
                    </Link>
                  </Button>
                )}
              </AlertDescription>
            </Alert>
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
                createLabel={canManage ? 'Watch folder' : undefined}
                onCreate={() => setDialog({})}
              />
            }
          />
        </div>
      )}
      <WatchFolderDialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} watch={dialog?.watch} />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="watched folder"
        entityName={deleting?.name}
        isLoading={del.isPending}
        description="Files stops watching this folder. The files already brought in stay in Files under their own retention."
        testIdPrefix="watch-delete"
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await del.mutateAsync(deleting.id);
            toast.success(`Stopped watching ${deleting.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete it: ${(e as Error).message}`);
          }
        }}
      />
    </PageLayout>
  );
}
