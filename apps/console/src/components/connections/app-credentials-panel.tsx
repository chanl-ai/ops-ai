'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Plus } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { credentialHref, secretShown } from '@/components/connections/credential-display';
import { CredentialEditDialog } from '@/components/connections/credential-edit-dialog';
import { NewAppCredentialDialog } from '@/components/connections/new-app-credential-dialog';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { type AppCredential, useAppCredentials } from '@/hooks/systems-queries';
import { shortDate } from '@/lib/format';

export const CREDENTIAL_STATUS: Record<AppCredential['status'], string> = { working: 'Working', not_tested: 'Not tested', failing: 'Failing' };

const columns = (onEdit: (c: AppCredential) => void, oneApp: boolean): ColumnDef<AppCredential>[] => [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
    cell: ({ row }) => (
      <Link href={credentialHref(row.original)} className="font-medium underline-offset-4 hover:underline" data-testid={`app-credential-open-${row.original.id}`}>
        {row.original.name}
      </Link>
    ),
  },
  ...(oneApp
    ? []
    : ([
        {
          id: 'app',
          accessorFn: (c) => c.app,
          header: ({ column }) => <DataTableColumnHeader column={column} title="App" />,
          cell: ({ row }) => (
            <Link href={`/integrations/apps/${encodeURIComponent(row.original.app)}`} className="underline-offset-4 hover:underline">
              {row.original.appName}
            </Link>
          ),
          filterFn: (row, id, value: string[]) => value.includes(row.getValue(id)),
        },
      ] satisfies ColumnDef<AppCredential>[])),
  {
    accessorKey: 'type',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />,
    cell: ({ row }) => <Badge variant={row.original.type === 'own' ? 'secondary' : 'default'}>{row.original.type === 'own' ? 'Your own app' : 'Ops AI’s app'}</Badge>,
  },
  {
    id: 'secret',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Client secret" />,
    cell: ({ row }) =>
      row.original.type === 'own' ? (
        <span className="font-mono text-xs" data-testid={`app-credential-secret-${row.original.id}`}>
          {secretShown(row.original)}
        </span>
      ) : (
        <span className="text-xs text-muted-foreground">Kept by Ops AI</span>
      ),
  },
  {
    id: 'permissions',
    accessorFn: (c) => c.permissions.map((p) => p.label).join(', '),
    header: ({ column }) => <DataTableColumnHeader column={column} title="Permissions" />,
    // A count, as the Credentials frame; the permissions themselves on hover.
    cell: ({ row }) => (
      <span className="tabular-nums" title={row.original.permissions.map((p) => p.label).join(', ')}>
        {row.original.permissions.length}
      </span>
    ),
  },
  { accessorKey: 'accounts', header: ({ column }) => <DataTableColumnHeader column={column} title="Accounts" />, cell: ({ row }) => <span className="tabular-nums">{row.original.accounts}</span> },
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <Badge variant="outline" data-status={row.original.status}>{CREDENTIAL_STATUS[row.original.status]}</Badge> },
  { accessorKey: 'created', header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />, cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.created ? shortDate(row.original.created) : '—'}</span> },
  {
    id: 'actions',
    header: () => null,
    // Only the team's own app is edited here; Ops AI's app is the install's.
    cell: ({ row }) =>
      row.original.type === 'own' ? (
        <Button size="sm" variant="ghost" onClick={() => onEdit(row.original)} data-testid={`app-credential-edit-${row.original.id}`}>
          Edit
        </Button>
      ) : null,
  },
];

/**
 * App credentials (U4): the OAuth clients the team's apps sign in with, the team's own and Ops AI's app of each app
 * using it, from GET /v1/app-credentials, grouped by app with an App filter (`?app=` opens it filtered). `app` fixes
 * the list to one app, as its page's Credentials tab shows it, and New app credential then starts on that app. A row
 * opens the credential's page; Edit changes any part of the team's own.
 */
export function AppCredentialsPanel({ app }: { app?: string }) {
  const creds = useAppCredentials(app);
  const router = useRouter();
  const params = useSearchParams();
  const [editing, setEditing] = React.useState<AppCredential | null>(null);
  const [adding, setAdding] = React.useState(false);
  const cols = React.useMemo(() => columns(setEditing, Boolean(app)), [app]);
  const wanted = app ? null : params.get('app');
  // A first answer that failed shows the error with Retry at once, not a skeleton while the retries run.
  if (!creds.data && (creds.isError || creds.failureCount > 0)) return <QueryError what="the auth configs" error={creds.error ?? creds.failureReason} onRetry={() => creds.refetch()} retrying={creds.isFetching} />;
  if (creds.isPending) return <PageSkeleton statCards={0} tableRows={4} />;
  const apps = [...new Map(creds.data.map((c) => [c.app, c.appName])).entries()].map(([value, label]) => ({ value, label }));
  const rows = [...creds.data].sort((a, b) => a.appName.localeCompare(b.appName) || a.name.localeCompare(b.name));
  return (
    <div className="flex flex-col gap-4" data-testid="app-credentials-panel">
      {/* The list answers team admins only, so the window that adds to it is theirs too. */}
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setAdding(true)} data-testid="new-app-credential">
          <Plus />
          New auth config
        </Button>
      </div>
      <DataTableWithViews
        columns={cols}
        data={rows.map((c) => ({ ...c, onRowClick: () => router.push(credentialHref(c)), href: credentialHref(c), rowTestId: `app-credential-row-${c.id}` }))}
        getRowId={(c) => c.id}
        searchColumn="name"
        searchPlaceholder="Search auth configs…"
        hideViewSwitcher
        filters={app ? undefined : [{ column: 'app', title: 'App', options: apps }]}
        initialColumnFilters={wanted ? [{ id: 'app', value: [wanted] }] : undefined}
        emptyState={<ListEmpty icon={KeyRound} noun="auth configs" filtered={false} description="No auth configs yet. Connecting an app that signs in uses Ops AI’s app; add your own with New auth config." />}
      />
      <CredentialEditDialog credentialId={editing?.id ?? null} onClose={() => setEditing(null)} />
      <NewAppCredentialDialog open={adding} onOpenChange={setAdding} app={app} />
    </div>
  );
}
