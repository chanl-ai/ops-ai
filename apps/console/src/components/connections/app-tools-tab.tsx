'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Minus, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { StopRowClick } from '@/components/shared/form-field';
import { ListEmpty } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { toolColumns } from '@/components/tools/tools-table';
import { type AppPage, useAddTools, useRemoveTool } from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';

type AppTool = AppPage['tools'][number];
type Row = AppTool & { id: string; access: 'read' | 'write' | 'workflow'; usedBy: { agents: { id: string; name: string }[]; workflows: { id: string; name: string }[] } | null };

/**
 * The app's Tools tab: the catalog of what the app offers, each tool Added or with Add to team, and a bulk Add for
 * the rows picked. Added tools are the team's: the Tools page lists them and the agent picker offers them; one never
 * added appears in neither and its calls are refused. It is the Tools page's own table, filtered to this app.
 */
export function ToolsTab({ app }: { app: AppPage }) {
  const add = useAddTools();
  const remove = useRemoveTool();
  const [asked, setAsked] = React.useState<string[]>([]);
  const [resetKey, setResetKey] = React.useState(0);
  const mayChange = Boolean(app.card.mayManage) && app.card.kind === 'plugin';
  const adding = (tools: AppTool[]) =>
    add.mutate(
      { appId: app.card.id, tools: tools.map((t) => t.name) },
      {
        onSuccess: (done) => {
          toast.success(tools.length === 1 ? `${tools[0].title} is added to the team` : `${tools.length} tools are added to the team`);
          setAsked(done.filter((t) => t.askedAtSignIn).map((t) => t.title));
          setResetKey((k) => k + 1);
        },
        onError: (e) => toast.error('Couldn’t add them', { description: e.message }),
      },
    );
  const removing = (t: AppTool) =>
    remove.mutate(
      { appId: app.card.id, tool: t.name },
      {
        onSuccess: () => (toast.success(`${t.title} is removed from the team`), setAsked((a) => a.filter((x) => x !== t.title))),
        onError: (e) => toast.error(`Couldn’t remove ${t.title}`, { description: e.message }),
      },
    );
  const rows: Row[] = app.tools.map((t) => ({ ...t, id: t.name, access: t.access as Row['access'], usedBy: t.usedBy ?? null }));
  const columns: ColumnDef<Row>[] = [
    ...(mayChange ? [selectColumn<Row>((t) => t.title)] : []),
    ...toolColumns<Row>(),
    {
      id: 'added',
      accessorFn: (t) => (t.added ? 'Added' : 'Not added'),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />,
      meta: { kind: 'status' },
      cell: ({ row: { original: t } }) => (
        <span className="flex flex-wrap items-center gap-2">
          {t.added ? (
            <Badge variant="secondary" data-testid={`app-tool-added-${t.name}`}>
              Added
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">Not added</span>
          )}
          {t.askedAtSignIn && (
            <Badge variant="outline" className="border-warning/40 bg-warning/10 text-warning-text" data-testid={`app-tool-asked-${t.name}`}>
              Asked at next sign-in
            </Badge>
          )}
        </span>
      ),
      filterFn: facetFilterFn,
    },
    {
      id: 'actions',
      enableHiding: false,
      cell: ({ row: { original: t } }) =>
        mayChange ? (
          <StopRowClick>
            {t.added ? (
              <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => removing(t)} data-testid={`app-tool-remove-${t.name}`}>
                <Minus />
                Remove from team
              </Button>
            ) : (
              <Button size="sm" variant="outline" disabled={add.isPending} onClick={() => adding([t])} data-testid={`app-tool-add-${t.name}`}>
                <Plus />
                Add to team
              </Button>
            )}
          </StopRowClick>
        ) : null,
    },
  ];
  const added = app.tools.filter((t) => t.added ?? true).length;
  return (
    <div className="flex flex-col gap-3" data-testid="app-tools">
      <p className="text-sm text-muted-foreground">
        {`What ${app.card.name} offers. Added tools are the ones agents and workflows in this team can pick. New apps start with their read tools added. ${added} of ${app.tools.length} added.`}
      </p>
      {asked.length > 0 && (
        <Alert data-testid="app-tool-asked">
          <AlertTitle>{`${asked.join(', ')} ${asked.length === 1 ? 'needs a permission' : 'need permissions'} the team account has not granted`}</AlertTitle>
          <AlertDescription>{`Each ${app.card.name} account is asked the next time it signs in. Until then, ${asked.length === 1 ? 'it cannot run' : 'they cannot run'} as that account.`}</AlertDescription>
        </Alert>
      )}
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(t) => t.name}
        searchColumn="name"
        searchPlaceholder="Search tools…"
        hideViewSwitcher
        selectionResetKey={resetKey}
        bulkActions={mayChange ? [{ label: 'Add to team', icon: Plus, onClick: (picked) => adding(picked.filter((t) => !t.added)) }] : undefined}
        filters={[
          { column: 'access', title: 'Read or write', options: ['Read', 'Write'].map((v) => ({ label: v, value: v })) },
          { column: 'added', title: 'Added', options: ['Added', 'Not added'].map((v) => ({ label: v, value: v })) },
        ]}
        emptyState={<ListEmpty icon={KeyRound} noun="tools" filtered={false} description={`${app.card.name} has no tools.`} />}
      />
    </div>
  );
}
