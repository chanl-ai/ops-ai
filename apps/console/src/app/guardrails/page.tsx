'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Archive, ArchiveRestore, ExternalLink, Send, ShieldBan, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { GuardrailFields, guardrailErrors, keptScopes, type GuardrailDraft, type GuardrailErrors } from '@/components/guardrails/guardrail-fields';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { announcePublish } from '@/components/shared/publish-result';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCreateGuardrail, useDeleteGuardrail, useRequestGuardrailPublish, useSetGuardrailStatus } from '@/hooks/guardrail-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useGuardrailsPage } from '@/hooks/queries';
import { useListParams } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';
import type { Guardrail } from '@/lib/types/domain';

/** Where the newest version stands: a draft to publish, waiting in Reviews, or published. */
function versionState(g: Guardrail): { label: string; variant: 'secondary' | 'outline' } {
  if (g.pendingRequestId) return { label: `v${g.version} in review`, variant: 'outline' };
  if (g.publishedVersion === g.version) return { label: `v${g.version} published`, variant: 'secondary' };
  return { label: `v${g.version} draft`, variant: 'outline' };
}

interface Actions {
  open: (g: Guardrail) => void;
  publish: (g: Guardrail) => void;
  status: (g: Guardrail) => void;
  remove: (g: Guardrail) => void;
}

function columns(on: Actions): ColumnDef<Guardrail>[] {
  return [
    selectColumn<Guardrail>((g) => g.name),
    idColumn<Guardrail>((g) => g.id),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Guardrail" />,
      cell: ({ row }) => (
        <div className="min-w-48">
          <div className="text-sm font-medium">{row.original.name}</div>
          <div className="text-xs text-muted-foreground">Owned by {row.original.owner}</div>
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'topics',
      header: 'Blocked topics',
      cell: ({ row }) => (
        <div className="flex max-w-80 flex-wrap gap-1">
          {row.original.config.topics.map((t) => (
            <Badge key={t} variant="outline" className="font-normal">
              {t}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      id: 'version',
      header: 'Version',
      cell: ({ row }) => {
        const s = versionState(row.original);
        return (
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={s.variant}>{s.label}</Badge>
            {row.original.status === 'deprecated' && <Badge variant="outline">Deprecated</Badge>}
          </div>
        );
      },
    },
    {
      id: 'usedBy',
      header: 'Pinned by',
      cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.usedBy.length ? row.original.usedBy.join(', ') : 'No agent'}</span>,
    },
    { accessorKey: 'updatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Updated" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{relativeTime(row.original.updatedAt)}</span> },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => {
        const g = row.original;
        const canPublish = !g.pendingRequestId && g.publishedVersion !== g.version && g.status === 'live';
        return (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Open', icon: ExternalLink, onClick: () => on.open(g) },
                ...(canPublish ? [{ label: `Publish v${g.version}`, icon: Send, onClick: () => on.publish(g) }] : []),
                g.status === 'live' ? { label: 'Deprecate', icon: Archive, onClick: () => on.status(g) } : { label: 'Make live', icon: ArchiveRestore, onClick: () => on.status(g) },
                { label: 'Delete', icon: Trash2, variant: 'destructive' as const, onClick: () => on.remove(g) },
              ]}
            />
          </StopRowClick>
        );
      },
      enableHiding: false,
    },
  ];
}

/** Create a guardrail: its name, owner and first version. It opens on its own page, where later versions are saved. */
function GuardrailDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; onCreated: (g: Guardrail) => void }) {
  const create = useCreateGuardrail();
  const [name, setName] = React.useState('');
  const [owner, setOwner] = React.useState('Compliance');
  const [draft, setDraft] = React.useState<GuardrailDraft>({ topics: [], scopes: {}, message: '', holdUntilChecked: false });
  const [errors, setErrors] = React.useState<GuardrailErrors & { name?: string }>({});
  React.useEffect(() => {
    if (!open) return;
    setName('');
    setOwner('Compliance');
    setDraft({ topics: [], scopes: {}, message: '', holdUntilChecked: false });
    setErrors({});
  }, [open]);
  const submit = async () => {
    const e = { name: name.trim() ? undefined : 'Name the guardrail.', ...guardrailErrors(draft) };
    setErrors(e);
    if (e.name || e.topics || e.message) return;
    try {
      const saved = await create.mutateAsync({ name: name.trim(), owner: owner.trim() || 'Compliance', topics: draft.topics, scopes: keptScopes(draft), message: draft.message.trim(), holdUntilChecked: draft.holdUntilChecked });
      toast.success(`Created ${saved.name}`, { description: 'Publish it to let agents pin this version.' });
      onOpenChange(false);
      onCreated(saved);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title="New guardrail"
      onSubmit={submit}
      description="Blocked topics are checked on the question and on the answer of every agent that pins the guardrail."
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={create.isPending} loadingText="Saving…" data-testid="guardrail-submit">
            Create guardrail
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField id="guardrail-name" label="Name" error={errors.name}>
            <Input id="guardrail-name" value={name} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. No investment advice" />
          </FormField>
          <FormField id="guardrail-owner" label="Owner">
            <Input id="guardrail-owner" value={owner} onChange={(e) => setOwner(e.target.value)} />
          </FormField>
        </div>
        <GuardrailFields value={draft} onChange={(d) => (setDraft(d), setErrors({}))} errors={errors} />
      </div>
    </DialogShell>
  );
}

export default function GuardrailsPage() {
  const router = useRouter();
  const list = useListParams('name');
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const query = useGuardrailsPage(list.params);
  const publish = useRequestGuardrailPublish();
  const setStatus = useSetGuardrailStatus();
  const remove = useDeleteGuardrail();
  const [creating, setCreating] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Guardrail | null>(null);
  const canBuild = useCanBuild();
  const allCols = React.useMemo(
    () =>
      columns({
        open: (g) => router.push(`/guardrails/${g.id}`),
        publish: async (g) => {
          try {
            const after = await publish.mutateAsync(g);
            announcePublish({ name: g.name, version: g.version, live: after.publishedVersion === g.version, liveNote: 'Agents can pin it now.', decidedBy: `A reviewer in ${g.owner}`, reviewId: after.pendingRequestId, openReview: (id) => router.push(`/reviews?review=${id}`) });
          } catch (e) {
            toast.error(`Couldn’t publish ${g.name}`, { description: (e as Error).message });
          }
        },
        status: async (g) => {
          const next = g.status === 'live' ? 'deprecated' : 'live';
          try {
            await setStatus.mutateAsync({ id: g.id, status: next });
            toast.success(next === 'deprecated' ? `Deprecated ${g.name}` : `${g.name} is live again`, { description: next === 'deprecated' ? 'It takes no new pins; agents that pin it keep enforcing their version.' : undefined });
          } catch (e) {
            toast.error(`Couldn’t change ${g.name}`, { description: (e as Error).message });
          }
        },
        remove: setDeleting,
      }),
    [publish, setStatus, router],
  );
  // Every row action changes the guardrail, so a viewer gets no actions column.
  const cols = React.useMemo(() => (canBuild ? allCols : allCols.filter((c) => c.id !== 'actions')), [allCols, canBuild]);

  return (
    <PageLayout
      icon={ShieldBan}
      title="Guardrails"
      description="Rules an agent pins by version. A question on a blocked topic gets the guardrail's message instead of an answer."
      actions={
        canBuild && (
          <Button onClick={() => setCreating(true)} data-testid="new-guardrail-button">
            New guardrail
          </Button>
        )
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError what="guardrails" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={(query.data?.data ?? []).map((g) => ({ ...g, onRowClick: (x: Guardrail) => router.push(`/guardrails/${x.id}`), href: `/guardrails/${g.id}` }))}
          getRowId={(g) => g.id}
          searchColumn="name"
          searchPlaceholder="Search names or owners…"
          onColumnFiltersChange={list.onColumnFiltersChange}
          serverPagination={{
            enabled: true,
            total: query.data?.pagination.total ?? 0,
            page: list.pagination.page,
            pageSize: list.pagination.pageSize,
            totalPages: query.data?.pagination.totalPages,
            onPaginationChange: list.setPagination,
            isLoading: query.isFetching && query.isPlaceholderData,
          }}
          filterResetKey={filterResetKey}
          hideViewSwitcher
          emptyState={<ListEmpty icon={ShieldBan} noun="guardrails" filtered={list.isFiltered} onClear={() => setFilterResetKey((k) => k + 1)} createLabel={canBuild ? 'New guardrail' : undefined} onCreate={() => setCreating(true)} description="Create one, publish it, then pin it on an agent's Guardrails section." />}
        />
      )}

      <GuardrailDialog open={creating} onOpenChange={setCreating} onCreated={(g) => router.push(`/guardrails/${g.id}`)} />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="guardrail"
        entityName={deleting?.name}
        description="Refused while an agent pins it; unpin it on each agent first."
        confirmText="Delete guardrail"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(deleting!.id);
            toast.success(`Deleted ${deleting!.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${deleting!.name}`, { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
