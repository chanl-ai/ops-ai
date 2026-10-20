'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { LayoutTemplate } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { WidgetStatusBadge } from '@/components/widgets/widget-status-badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useListParams } from '@/hooks/use-list-params';
import { useCanBuild } from '@/hooks/me-queries';
import { useCreateWidget, useWidgetTemplatesPage } from '@/hooks/widget-queries';
import { relativeTime } from '@/lib/format';
import type { WidgetTemplate } from '@/lib/types/widgets';

type Row = WidgetTemplate & { onRowClick: (w: WidgetTemplate) => void; href: string };

const columns: ColumnDef<Row>[] = [
  selectColumn<Row>((w) => w.name),
  idColumn<Row>((w) => w.widgetId),
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Widget" />,
    cell: ({ row }) => (
      <div className="min-w-56 max-w-xl">
        <div className="text-sm font-medium">{row.original.name}</div>
        <div className="line-clamp-2 text-xs text-muted-foreground">{row.original.useWhen}</div>
      </div>
    ),
    enableHiding: false,
  },
  { id: 'status', header: 'Version', cell: ({ row }) => <WidgetStatusBadge widget={row.original} /> },
  {
    accessorKey: 'updatedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Updated" />,
    cell: ({ row }) => (
      <span className="text-sm whitespace-nowrap text-muted-foreground">
        {row.original.updatedAt ? relativeTime(row.original.updatedAt) : '—'}
        {row.original.updatedBy ? ` · ${row.original.updatedBy}` : ''}
      </span>
    ),
  },
];

/** A new widget starts as a card with a title bound to one field, so the preview shows something at once. */
const STARTER = {
  tree: { type: 'card', title: { $bind: '/title' }, children: [{ type: 'text', text: { $bind: '/summary' } }] },
  dataSchema: { type: 'object', additionalProperties: false, required: ['title'], properties: { title: { type: 'string', maxLength: 120 }, summary: { type: 'string', maxLength: 400 } } },
  sample: { title: 'Example title', summary: 'One line the agent fills in.' },
} as const;

function NewWidgetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const create = useCreateWidget();
  const [name, setName] = React.useState('');
  const [useWhen, setUseWhen] = React.useState('');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) (setName(''), setUseWhen(''), setError(undefined));
  }, [open]);
  const submit = async () => {
    if (!name.trim() || !useWhen.trim()) return setError(!name.trim() ? 'Name the widget.' : 'Say when the agent should use it.');
    try {
      const w = await create.mutateAsync({ name: name.trim(), useWhen: useWhen.trim(), ...structuredClone(STARTER) } as never);
      onOpenChange(false);
      router.push(`/widgets/${w.widgetId}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New widget"
      onSubmit={submit}
      description="Name it and say when an agent should use it. You lay it out on the next page."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={create.isPending} loadingText="Creating…" data-testid="new-widget-submit">
            Create widget
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="widget-name" label="Name" error={!name.trim() ? error : undefined}>
          <Input id="widget-name" value={name} onChange={(e) => (setName(e.target.value), setError(undefined))} placeholder="e.g. Card dispute summary" />
        </FormField>
        <FormField id="widget-use-when" label="When the agent uses it" hint="The agent reads this line to decide when to show the widget." error={name.trim() ? error : undefined}>
          <Textarea id="widget-use-when" rows={3} value={useWhen} onChange={(e) => (setUseWhen(e.target.value), setError(undefined))} placeholder="e.g. The person asks where a card dispute stands." />
        </FormField>
      </div>
    </DialogShell>
  );
}

export default function WidgetsPage() {
  const router = useRouter();
  const list = useListParams('name');
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const query = useWidgetTemplatesPage(list.params);
  const [creating, setCreating] = React.useState(false);
  const canBuild = useCanBuild();
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((w) => ({ ...w, onRowClick: (x: WidgetTemplate) => router.push(`/widgets/${x.widgetId}`), href: `/widgets/${w.widgetId}` })), [query.data, router]);

  return (
    <PageLayout
      icon={LayoutTemplate}
      title="Widgets"
      description="Reusable answer layouts an agent fills in chat. Each version goes live only after a second person approves it."
      actions={
        canBuild && (
          <Button onClick={() => setCreating(true)} data-testid="new-widget-button">
            New widget
          </Button>
        )
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError what="widgets" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={rows}
          getRowId={(w) => w.widgetId}
          searchColumn="name"
          searchPlaceholder="Search widgets…"
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
          emptyState={<ListEmpty icon={LayoutTemplate} noun="widgets" filtered={list.isFiltered} onClear={() => setFilterResetKey((k) => k + 1)} createLabel={canBuild ? 'New widget' : undefined} onCreate={() => setCreating(true)} description="Create one, lay it out from the building blocks, and publish it so agents can pin it." />}
        />
      )}
      <NewWidgetDialog open={creating} onOpenChange={(o) => (o ? setCreating(true) : (setCreating(false), void toast.dismiss()))} />
    </PageLayout>
  );
}
