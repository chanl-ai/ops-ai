'use client';

import * as React from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, CalendarClock, Clock, Files, FolderOpen, Scale, ShieldX, Trash2, Unlink } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { fileIcon, PURPOSE_LABEL, RetentionCell, SCAN_LABEL, ScanText, SENSITIVITY_LABEL, SensitivityBadge } from '@/components/files/file-meta';
import { FileSheet } from '@/components/files/file-sheet';
import { LegalHoldDialog } from '@/components/files/legal-hold-dialog';
import { PageLayout } from '@/components/page-layout';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { selectColumn } from '@/components/shared/select-column';
import { Button } from '@/components/ui/button';
import { useFile, useFiles, useRemoveFiles, useSetLegalHold, useSetRetention, useStorageSettings } from '@/hooks/file-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { bytes, plural, relativeTime } from '@/lib/format';
import type { FileFilters, FilePurpose, FileRecord, FileSensitivity, FileView, ScanStatus } from '@/lib/types/files';

type Row = FileRecord & { onRowClick: (f: FileRecord) => void };

const VIEW_EMPTY: Record<FileView, string> = {
  all: 'Files appear here when someone uploads a source, attaches a file in chat, imports a CSV, or a mailbox receives an attachment.',
  quarantined: 'No file failed its malware scan.',
  legal_hold: 'No file is under legal hold.',
  unreferenced: 'Every file older than 30 days is still used by a source, case, chat or test set.',
  expiring: 'No file reaches its delete-after date in the next 30 days.',
};

function columns(onHold: (f: FileRecord) => void, onDelete: (f: FileRecord) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((f) => f.name),
    {
      // Holds every searched field so the table's own filter keeps the rows the server matched.
      id: 'name',
      accessorFn: (f) => `${f.name} ${f.uploadedBy} ${f.team} ${f.digest}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
      cell: ({ row }) => {
        const Icon = fileIcon(row.original.name);
        return (
          <div className="flex w-64 max-w-64 items-center gap-2.5" title={row.original.name}>
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.name}</div>
              <div className="text-xs text-muted-foreground tabular-nums">{bytes(row.original.size)}{row.original.versionCount > 1 && ` · ${plural(row.original.versionCount, 'version')}`}</div>
            </div>
          </div>
        );
      },
      enableHiding: false,
    },
    { accessorKey: 'purpose', header: ({ column }) => <DataTableColumnHeader column={column} title="Purpose" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{PURPOSE_LABEL[row.original.purpose]}</span>, filterFn: facetFilterFn },
    { accessorKey: 'team', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{row.original.team}</span>, filterFn: facetFilterFn },
    { accessorKey: 'size', header: ({ column }) => <DataTableColumnHeader column={column} title="Size" />, cell: ({ row }) => <span className="text-xs whitespace-nowrap tabular-nums">{bytes(row.original.size)}</span> },
    { accessorKey: 'sensitivity', header: ({ column }) => <DataTableColumnHeader column={column} title="Sensitivity" />, cell: ({ row }) => <SensitivityBadge value={row.original.sensitivity} suggested={row.original.sensitivitySuggested} />, filterFn: facetFilterFn },
    { id: 'scan', accessorFn: (f) => f.scan.status, header: ({ column }) => <DataTableColumnHeader column={column} title="Scan" />, cell: ({ row }) => <ScanText status={row.original.scan.status} detail={row.original.scan.detail} />, filterFn: facetFilterFn },
    { id: 'retention', accessorFn: (f) => f.retention.classId, header: ({ column }) => <DataTableColumnHeader column={column} title="Retention" />, cell: ({ row }) => <RetentionCell file={row.original} />, filterFn: facetFilterFn },
    {
      id: 'references',
      accessorFn: (f) => f.referenceCount,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Used by" />,
      cell: ({ row }) => (row.original.referenceCount ? <span className="text-sm tabular-nums">{plural(row.original.referenceCount, 'record')}</span> : <span className="text-xs text-muted-foreground">Nothing</span>),
    },
    {
      id: 'uploaded',
      accessorFn: (f) => f.uploadedAt,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Uploaded" />,
      cell: ({ row }) => (
        <div className="flex w-36 flex-col">
          <span className="truncate text-sm">{row.original.uploadedBy}</span>
          <span className="text-xs text-muted-foreground">{relativeTime(row.original.uploadedAt)}</span>
        </div>
      ),
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Open', icon: ArrowRight, onClick: (r) => r.original.onRowClick(r.original) },
              { label: row.original.legalHold ? 'Release legal hold' : 'Place legal hold', icon: Scale, onClick: (r) => onHold(r.original) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => onDelete(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function FilesPage() {
  const [view, setView] = React.useState<FileView>('all');
  const list = useListParams<FileFilters>('name');
  const query = useFiles({ ...list.params, view });
  const storage = useStorageSettings();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  // The open file lives in ?file= so cases, sources and toasts can link straight to it.
  const activeId = searchParams.get('file');
  const setActiveId = React.useCallback((id: string | null) => router.replace(id ? `${pathname}?file=${id}` : pathname, { scroll: false }), [router, pathname]);
  const active = useFile(activeId);

  const setRetention = useSetRetention();
  const setHold = useSetLegalHold();
  const remove = useRemoveFiles();
  const [retaining, setRetaining] = React.useState<FileRecord[] | null>(null);
  const [holding, setHolding] = React.useState<{ rows: FileRecord[]; hold: boolean } | null>(null);
  const [deleting, setDeleting] = React.useState<FileRecord[] | null>(null);
  const shownRetaining = useSticky(retaining);
  const shownHolding = useSticky(holding);
  const shownDeleting = useSticky(deleting);
  const [resetKey, setResetKey] = React.useState(0);
  const [filterResetKey, setFilterResetKey] = React.useState(0);

  const rows0 = query.data?.data ?? [];
  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const classes = storage.data?.retentionClasses ?? [];
  const className = (id: string) => classes.find((c) => c.id === id)?.name ?? id;
  const cols = React.useMemo(() => columns((f) => setHolding({ rows: [f], hold: !f.legalHold }), (f) => setDeleting([f])), []);
  const rows: Row[] = React.useMemo(() => rows0.map((f) => ({ ...f, onRowClick: (x: FileRecord) => setActiveId(x.id) })), [rows0, setActiveId]);
  const optionsOf = <K extends string>(key: string, label: (k: K) => string) => Object.keys(facets[key] ?? {}).map((k) => ({ label: label(k as K), value: k, count: facets[key]?.[k] ?? 0 }));
  const index = rows.findIndex((r) => r.id === activeId);
  const nameOf = (list: FileRecord[] | null | undefined) => (id: string) => list?.find((f) => f.id === id)?.name ?? id;
  const done = () => setResetKey((k) => k + 1);

  return (
    <PageLayout icon={FolderOpen} title="Files" description="Every file the platform stores: uploads, mail attachments, imports, exports and sealed evidence, with scan, retention and what uses each">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={10} />
      ) : query.isError && !query.data ? (
        <QueryError what="files" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="File views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}`, icon: Files },
              { id: 'quarantined', label: `Quarantined · ${counts?.quarantined ?? 0}`, icon: ShieldX },
              { id: 'legal_hold', label: `Under legal hold · ${counts?.legal_hold ?? 0}`, icon: Scale },
              { id: 'unreferenced', label: `Unreferenced · ${counts?.unreferenced ?? 0}`, icon: Unlink },
              { id: 'expiring', label: `Expiring in 30 days · ${counts?.expiring ?? 0}`, icon: CalendarClock },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(vid) => {
              setView(vid as FileView);
              list.reset();
              done();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <DataTableWithViews
            columns={cols}
            data={rows}
            getRowId={(r) => r.id}
            initialColumnVisibility={{ size: false }}
            searchColumn="name"
            searchPlaceholder="Search names, uploaders or digests…"
            filters={[
              { column: 'purpose', title: 'Purpose', options: optionsOf<FilePurpose>('purpose', (k) => PURPOSE_LABEL[k] ?? k) },
              { column: 'team', title: 'Team', options: optionsOf<string>('team', (k) => k) },
              { column: 'sensitivity', title: 'Sensitivity', options: optionsOf<FileSensitivity>('sensitivity', (k) => SENSITIVITY_LABEL[k] ?? k) },
              { column: 'scan', title: 'Scan', options: optionsOf<ScanStatus>('scan', (k) => SCAN_LABEL[k] ?? k) },
              { column: 'retention', title: 'Retention', options: optionsOf<string>('retention', className) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={resetKey}
            filterResetKey={filterResetKey}
            bulkActions={[
              { label: 'Set retention', icon: Clock, onClick: (rs) => setRetaining(rs) },
              { label: 'Place legal hold', icon: Scale, onClick: (rs) => setHolding({ rows: rs, hold: true }) },
              { label: 'Release legal hold', icon: Scale, onClick: (rs) => setHolding({ rows: rs, hold: false }) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rs) => setDeleting(rs) },
            ]}
            serverPagination={{
              enabled: true,
              total: query.data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: query.data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={Files} noun={view === 'all' ? 'files' : 'files in this view'} filtered={list.isFiltered} onClear={() => setFilterResetKey((k) => k + 1)} description={VIEW_EMPTY[view]} />}
          />
        </div>
      )}

      <FileSheet
        open={!!activeId}
        onOpenChange={(o) => !o && setActiveId(null)}
        file={active.data && active.data.id === activeId ? active.data : undefined}
        loading={active.isPending}
        error={active.error}
        onRetry={() => active.refetch()}
        navigation={
          index >= 0
            ? {
                currentIndex: index + (list.pagination.page - 1) * list.pagination.pageSize,
                totalCount: Math.max(query.data?.pagination.total ?? rows.length, 1),
                onPrev: index > 0 ? () => setActiveId(rows[index - 1].id) : undefined,
                onNext: index < rows.length - 1 ? () => setActiveId(rows[index + 1].id) : undefined,
              }
            : undefined
        }
        onHold={(f, hold) => setHolding({ rows: [f], hold })}
        onDelete={(f) => setDeleting([f])}
      />

      <BulkFieldDialog
        open={!!retaining}
        onOpenChange={(o) => !o && setRetaining(null)}
        title="Set retention"
        description="Files are deleted when their retention class ends. A class only applies to the kinds of file it lists."
        fieldLabel="Retention class"
        options={classes.map((c) => c.name)}
        names={(shownRetaining ?? []).map((f) => f.name)}
        notice="Retention can only be made longer or stricter. Immutable evidence, files under legal hold and files the class does not apply to are skipped and named."
        confirmLabel="Set retention"
        isPending={setRetention.isPending}
        onConfirm={async (name) => {
          const cls = classes.find((c) => c.name === name);
          if (!cls || !retaining) return;
          const res = await setRetention.mutateAsync({ ids: retaining.map((f) => f.id), classId: cls.id });
          toastBulk(res, 'Updated retention on', 'file', nameOf(shownRetaining));
          done();
        }}
      />
      <LegalHoldDialog
        open={!!holding}
        onOpenChange={(o) => !o && setHolding(null)}
        hold={shownHolding?.hold ?? true}
        names={(shownHolding?.rows ?? []).map((f) => f.name)}
        isPending={setHold.isPending}
        onConfirm={async (reason) => {
          if (!holding) return;
          const res = await setHold.mutateAsync({ ids: holding.rows.map((f) => f.id), hold: holding.hold, reason });
          toastBulk(res, holding.hold ? 'Placed a legal hold on' : 'Released the legal hold on', 'file', nameOf(holding.rows));
          done();
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="file"
        entityName={shownDeleting?.length === 1 ? shownDeleting[0].name : undefined}
        count={shownDeleting?.length}
        description="Every version is deleted from storage. Files still used by a source, case, chat or test set, under legal hold, or inside a retention period that must run out are skipped and named."
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            const res = await remove.mutateAsync(deleting.map((f) => f.id));
            toastBulk(res, 'Deleted', 'file', nameOf(deleting));
            if (activeId && res.updated.includes(activeId)) setActiveId(null);
            setDeleting(null);
            done();
          } catch (e) {
            toast.error('Couldn’t delete', { description: (e as Error).message });
          }
        }}
      />
      {/* Footer link for admins; storage itself is configured in Settings. */}
      {storage.data && (
        <p className="text-xs text-muted-foreground">
          Signed download links last {storage.data.signedUrlMinutes} minutes.{' '}
          <Button variant="link" className="h-auto p-0 text-xs" onClick={() => router.push('/settings/storage')}>
            Storage settings
          </Button>
        </p>
      )}
    </PageLayout>
  );
}
