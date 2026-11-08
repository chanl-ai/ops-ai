'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Clock, Pencil, Plus, ShieldCheck, ShieldQuestion, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { GatePolicyDialog } from '@/components/reviews/gate-policy-dialog';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { BulkFieldDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { selectColumn } from '@/components/shared/select-column';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ReadOnlyNotice } from '@/components/shared/builder-only';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { useBulkDeletePolicies, useBulkUpdatePolicies, useCreatePolicy, useDeletePolicy, useLookups, usePolicies, useUpdatePolicy } from '@/hooks/queries';
import { useCan } from '@/hooks/me-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { conditionInWords } from '@/lib/condition-words';
import { count } from '@/lib/format';
import type { GatePolicy } from '@/lib/types/domain';
import type { PolicyFilters } from '@/lib/types/query';
import { serverPagination } from '@/components/shared/server-pagination';

type Row = GatePolicy & { onRowClick: (p: GatePolicy) => void };

function columns(onEdit: (p: GatePolicy) => void, onDelete: (p: GatePolicy) => void, canManage: boolean): ColumnDef<Row>[] {
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
      // In words a person reads; the rule as written stays one click away.
      cell: ({ row }) => (
        // Table cells keep text on one line; a rule wraps within its column instead of running into the next.
        <div className="max-w-80 min-w-48 text-sm whitespace-normal">
          <div>{conditionInWords(row.original.condition)}</div>
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Rule</summary>
            <code className="font-mono break-words">{row.original.condition}</code>
          </details>
        </div>
      ),
      enableSorting: false,
    },
    { accessorKey: 'reviewers', header: ({ column }) => <DataTableColumnHeader column={column} title="Reviewers" /> },
    {
      accessorKey: 'fourEyes',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Reviewers" />,
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
    ...(canManage ? [{
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
    } satisfies ColumnDef<Row>] : []),
  ];
}

export default function GatePoliciesPage() {
  const list = useListParams<PolicyFilters>('name');
  // Everyone in the team reads the gates (reviews.view); whoever manages the team's reviews changes them.
  const canManage = useCan('reviews', 'manage') === true;
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
  // Row click would open the editor, whose Save sits outside the disabled gate.
  const openEdit = React.useCallback(() => undefined, []);
  const cols = React.useMemo(() => columns(openEdit, setDeleting, canManage), [openEdit, canManage]);
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((p) => ({ ...p, onRowClick: openEdit })), [query.data, openEdit]);
  const facets = query.data?.facets ?? {};

  return (
    <SettingsPageLayout
      sample
      section="Gate policies"
      description="Who reviews at each gate, how long they have, and what happens when time runs out."
      actions={
        canManage && (
          <Button onClick={openCreate}>
            <Plus className="size-4" /> New gate
          </Button>
        )
      }
    >
      <ReadOnlyNotice noun="gates" area="reviews" canEdit={canManage} />
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={7} />
      ) : query.isError && !query.data ? (
        <QueryError what="gate policies" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
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
          bulkActions={canManage ? [
            { label: 'Set SLA', icon: Clock, variant: 'outline', onClick: (rows) => setBulk({ kind: 'sla', rows }) },
            { label: 'Change reviewers', icon: Users, variant: 'outline', onClick: (rows) => setBulk({ kind: 'reviewers', rows }) },
            { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rows) => setBulk({ kind: 'delete', rows }) },
          ] : undefined}
          serverPagination={serverPagination(list, query)}
          emptyState={
            <ListEmpty
              icon={ShieldQuestion}
              noun="gates"
              filtered={list.isFiltered}
              description="Without a gate, every run finishes without a person. Add one where a decision needs sign-off."
              createLabel={canManage ? 'New gate' : undefined}
              onCreate={canManage ? openCreate : undefined}
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
    </SettingsPageLayout>
  );
}
