'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound } from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ListEmpty } from '@/components/shared/query-states';
import { StopRowClick } from '@/components/shared/form-field';
import { type AppPage, useSwitchTool } from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';

type AppTool = AppPage['tools'][number];

/**
 * The app's Tools tab: what the team lets its agents and workflows use, one switch per tool. Switched-on tools are
 * the ones the agent tool picker offers; a call to one that is off is refused. Turning on a tool whose permission the
 * team account has not granted says it is asked at the next sign-in.
 */
export function ToolsTab({ app }: { app: AppPage }) {
  const switchTool = useSwitchTool();
  const [asked, setAsked] = React.useState<AppTool | null>(null);
  const mayChange = Boolean(app.card.mayManage) && app.card.kind === 'plugin';
  const flip = (t: AppTool, on: boolean) =>
    switchTool.mutate(
      { appId: app.card.id, tool: t.name, on },
      {
        onSuccess: (r) => setAsked(r.askedAtSignIn ? r : null),
        onError: (e) => toast.error(`Couldn’t switch ${t.title} ${on ? 'on' : 'off'}`, { description: e.message }),
      },
    );
  const columns: ColumnDef<AppTool>[] = [
    {
      accessorKey: 'title',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tool" />,
      meta: { kind: 'name' },
      cell: ({ row: { original: t } }) => (
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{t.title}</span>
          <code className="truncate text-xs text-muted-foreground">{t.name}</code>
        </span>
      ),
    },
    {
      id: 'kind',
      accessorFn: (t) => (t.access === 'write' ? 'Write' : 'Read'),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Kind" />,
      meta: { kind: 'status' },
      cell: ({ row: { original: t } }) => <Badge variant={t.access === 'write' ? 'default' : 'secondary'}>{t.access === 'write' ? 'Write' : 'Read'}</Badge>,
      filterFn: facetFilterFn,
    },
    {
      id: 'on',
      accessorFn: (t) => (t.on ? 'On' : 'Off'),
      header: ({ column }) => <DataTableColumnHeader column={column} title="On for the team" />,
      meta: { kind: 'status' },
      cell: ({ row: { original: t } }) => (
        <StopRowClick align="start">
          <span className="flex flex-wrap items-center gap-2">
            <Switch
              checked={t.on ?? true}
              disabled={!mayChange || switchTool.isPending}
              onCheckedChange={(on) => flip(t, on)}
              aria-label={`${t.title} on for the team`}
              data-testid={`app-tool-on-${t.name}`}
            />
            {t.askedAtSignIn && (
              <Badge variant="outline" className="border-warning/40 bg-warning/10 text-warning-text" data-testid={`app-tool-asked-${t.name}`}>
                Asked at next sign-in
              </Badge>
            )}
          </span>
        </StopRowClick>
      ),
      filterFn: facetFilterFn,
    },
  ];
  const on = app.tools.filter((t) => t.on ?? true).length;
  return (
    <div className="flex flex-col gap-3" data-testid="app-tools">
      <p className="text-sm text-muted-foreground">
        {`Switched-on tools are the ones agents and workflows in this team can pick. New apps start with read tools on and write tools off. ${on} of ${app.tools.length} on.`}
      </p>
      {asked && (
        <Alert data-testid="app-tool-asked">
          <AlertTitle>{`${asked.title} needs a permission the team account has not granted`}</AlertTitle>
          <AlertDescription>{`Each ${app.card.name} account is asked for it the next time it signs in. Until then, ${asked.title} cannot run as that account.`}</AlertDescription>
        </Alert>
      )}
      <DataTableWithViews
        columns={columns}
        data={app.tools}
        getRowId={(t) => t.name}
        searchColumn="title"
        searchPlaceholder="Search tools…"
        hideViewSwitcher
        filters={[
          { column: 'kind', title: 'Read or write', options: ['Read', 'Write'].map((v) => ({ label: v, value: v })) },
          { column: 'on', title: 'On or off', options: ['On', 'Off'].map((v) => ({ label: v, value: v })) },
        ]}
        emptyState={<ListEmpty icon={KeyRound} noun="tools" filtered={false} description={`${app.card.name} has no tools.`} />}
      />
    </div>
  );
}
