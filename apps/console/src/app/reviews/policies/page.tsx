'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Clock, Pencil, Plus, ShieldCheck, ShieldQuestion, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { GatePolicyDialog } from '@/components/reviews/gate-policy-dialog';
import { ReviewsPageLayout } from '@/components/reviews/reviews-page-layout';
import { BulkFieldDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { selectColumn } from '@/components/shared/select-column';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { useBulkDeletePolicies, useBulkUpdatePolicies, useCreatePolicy, useDeletePolicy, useLookups, usePolicies, useUpdatePolicy } from '@/hooks/queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count } from '@/lib/format';
import type { GatePolicy } from '@/lib/types/domain';
import type { PolicyFilters } from '@/lib/types/query';

type Row = GatePolicy & { onRowClick: (p: GatePolicy) => void };

function columns(onEdit: (p: GatePolicy) => void, onDelete: (p: GatePolicy) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((p) => p.name),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Gate" />,
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      enableHiding: false,
    },
    {
      accessorKey: 'workflowId',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />,
      cell: ({ row }) => <span className="text-muted-foreground">{row.original.workflowName}</span>,
      filterFn: facetFilterFn,
      enableSorting: false,
    },
    {
      accessorKey: 'condition',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Pauses the run when" />,
      cell: ({ row }) => <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{row.original.condition}</code>,
      enableSorting: false,
    },
    { accessorKey: 'reviewers', header: ({ column }) => <DataTableColumnHeader column={column} title="Reviewers" /> },
    {
      accessorKey: 'fourEyes',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Approvers" />,
      cell: ({ row }) =>
        row.original.fourEyes ? (
          <span className="inline-flex items-center gap-1 text-xs">
            <ShieldCheck className="size-3.5 text-primary" /> 2
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">1</span>
        ),
    },
    { accessorKey: 'sla', header: ({ column }) => <DataTableColumnHeader column={column} title="SLA" />, enableSorting: false },
    {
      accessorKey: 'onTimeout',
      header: ({ column }) => <DataTableColumnHeader column={column} title="On timeout" />,
      cell: ({ row }) => <span className="text-muted-foreground">{row.original.onTimeout}</span>,
      enableSorting: false,
    },
    {
      accessorKey: 'hits7d',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Paused runs · 7d" />,
      cell: ({ row }) => <span className="tabular-nums">{count(row.original.hits7d)}</span>,
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Edit', icon: Pencil, onClick: (r) => onEdit(r.original) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => onDelete(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function GatePoliciesPage() {
  const list = useListParams<PolicyFilters>('name');
  const query = usePolicies(list.params);
  const { data: lookups } = useLookups();
  const create = useCreatePolicy();
  const update = useUpdatePolicy();
  const remove = useDeletePolicy();
  const [dialog, setDialog] = React.useState<{ open: boolean; policy: GatePolicy | null }>({ open: false, policy: null });
  const [deleting, setDeleting] = React.useState<GatePolicy | null>(null);
  const bulkUpdate = useBulkUpdatePolicies();
  const bulkDelete = useBulkDeletePolicies();
  const [bulk, setBulk] = React.useState<{ kind: 'sla' | 'reviewers' | 'delete'; rows: GatePolicy[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((p) => p.name);
  const nameOf = (id: string) => shown?.rows.find((p) => p.id === id)?.name ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };

  const openCreate = () => setDialog({ open: true, policy: null });
  const openEdit = React.useCallback((p: GatePolicy) => setDialog({ open: true, policy: p }), []);
  const cols = React.useMemo(() => columns(openEdit, setDeleting), [openEdit]);
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((p) => ({ ...p, onRowClick: openEdit })), [query.data, openEdit]);
  const facets = query.data?.facets ?? {};

  return (
    <ReviewsPageLayout
      actions={
        <Button onClick={openCreate}>
          <Plus className="size-4" /> New gate
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={7} />
      ) : query.isError && !query.data ? (
        <QueryError what="gate policies" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(r) => r.id}
          initialColumnVisibility={{ onTimeout: false, sla: false }}
          searchColumn="name"
          searchPlaceholder="Search gates…"
          filters={[
            {
              column: 'workflowId',
              title: 'Workflow',
              options: (lookups?.workflows ?? []).map((w) => ({ label: w.name, value: w.id, count: facets.workflowId?.[w.id] ?? 0 })),
            },
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={[
            { label: 'Set SLA', icon: Clock, variant: 'outline', onClick: (rows) => setBulk({ kind: 'sla', rows }) },
            { label: 'Change reviewers', icon: Users, variant: 'outline', onClick: (rows) => setBulk({ kind: 'reviewers', rows }) },
            { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rows) => setBulk({ kind: 'delete', rows }) },
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
          emptyState={
            <ListEmpty
              icon={ShieldQuestion}
              noun="gates"
              filtered={list.isFiltered}
              description="Without a gate, every run finishes without a person. Add one where a decision needs sign-off."
              createLabel="New gate"
              onCreate={openCreate}
            />
          }
        />
      )}

      <GatePolicyDialog
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        policy={dialog.policy}
        lookups={lookups}
        isPending={create.isPending || update.isPending}
        onSubmit={async (input) => {
          if (dialog.policy) {
            await update.mutateAsync({ id: dialog.policy.id, ...input });
            toast.success(`Saved ${input.name}`, { description: 'New runs use the updated gate.' });
          } else {
            await create.mutateAsync(input);
            toast.success(`Created ${input.name}`);
          }
        }}
      />

      <BulkFieldDialog
        open={bulk?.kind === 'sla' || bulk?.kind === 'reviewers'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={shown?.kind === 'sla' ? `Set SLA on ${names.length} gates` : `Change reviewers on ${names.length} gates`}
        description="Applies to reviews these gates raise from now on. Open reviews keep their current SLA and assignee."
        fieldLabel={shown?.kind === 'sla' ? 'SLA' : 'Reviewer group'}
        options={shown?.kind === 'sla' ? (lookups?.slaOptions ?? []) : (lookups?.reviewerGroups ?? [])}
        names={names}
        confirmLabel="Apply"
        isPending={bulkUpdate.isPending}
        onConfirm={async (value) => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((p) => p.id), patch: bulk!.kind === 'sla' ? { sla: value } : { reviewers: value } });
          toastBulk(res, 'Updated', 'gate', nameOf);
          finish();
        }}
      />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="gate"
        count={names.length}
        description="Runs that match these conditions will finish without a person. Open reviews they created stay in the queue."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          const res = await bulkDelete.mutateAsync(bulk!.rows.map((p) => p.id));
          toastBulk(res, 'Deleted', 'gate', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>

      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="gate"
        entityName={deleting?.name}
        description="Runs that match this condition will finish without a person. Open reviews it already created stay in the queue."
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.id);
            toast.success(`Deleted ${deleting.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error('Couldn’t delete the gate', { description: (e as Error).message });
          }
        }}
      />
    </ReviewsPageLayout>
  );
}
