'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Minus, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { StopRowClick } from '@/components/shared/form-field';
import { ListEmpty } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { toolColumns } from '@/components/tools/tools-table';
import { type AppPage, useAddTools, useRemoveTool } from '@/hooks/systems-queries';

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
  const [picked, setPicked] = React.useState(0);
  const mayChange = Boolean(app.card.mayManage) && app.card.kind === 'plugin';
  const adding = (tools: AppTool[]) =>
    add.mutate(
      { appId: app.card.id, tools: tools.map((t) => t.name) },
      {
        onSuccess: (done) => {
          toast.success(tools.length === 1 ? `${tools[0].title} is added to the team` : `${tools.length} tools are added to the team`);
          setPicked(0);
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
    // Only a tool not yet added can be picked: the bulk action adds, so an added row in the pick would do nothing.
    ...(mayChange ? [selectColumn<Row>((t) => t.title, (t) => !t.added)] : []),
    ...toolColumns<Row>(),
    {
      id: 'actions',
      enableHiding: false,
      meta: { className: 'w-px whitespace-nowrap text-right' },
      cell: ({ row: { original: t } }) => (
        <StopRowClick>
          <span className="flex items-center justify-end gap-2">
            {t.askedAtSignIn && (
              <Badge variant="outline" className="border-warning/40 bg-warning/10 text-warning-text" data-testid={`app-tool-asked-${t.name}`}>
                Asked at next sign-in
              </Badge>
            )}
            {mayChange &&
              (t.added ? (
                <Button size="sm" variant="ghost" className="text-muted-foreground" title="Remove from team" disabled={remove.isPending} onClick={() => removing(t)} data-testid={`app-tool-remove-${t.name}`}>
                  <Minus />
                  Remove
                </Button>
              ) : (
                <Button size="sm" variant="outline" title="Add to team" disabled={add.isPending} onClick={() => adding([t])} data-testid={`app-tool-add-${t.name}`}>
                  <Plus />
                  Add
                </Button>
              ))}
          </span>
        </StopRowClick>
      ),
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
        onSelectionChange={(rows) => setPicked(rows.length)}
        bulkActions={mayChange ? [{ label: `Add (${picked})`, icon: Plus, onClick: (rows) => adding(rows) }] : undefined}
        filters={[{ column: 'access', title: 'Read or write', options: ['Read', 'Write'].map((v) => ({ label: v, value: v })) }]}
        emptyState={<ListEmpty icon={KeyRound} noun="tools" filtered={false} description={`${app.card.name} has no tools.`} />}
      />
    </div>
  );
}
