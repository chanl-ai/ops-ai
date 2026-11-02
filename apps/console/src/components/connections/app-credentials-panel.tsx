'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { type AppCredential, useAppCredentials, useSetAppSecret } from '@/hooks/systems-queries';
import { shortDate } from '@/lib/format';

const STATUS: Record<AppCredential['status'], string> = { working: 'Working', not_tested: 'Not tested', failing: 'Failing' };
/** The plugin an app credential belongs to (its app is plugin:<id>); a custom app has none, and no secret to replace here. */
const pluginOf = (c: AppCredential) => (c.app.startsWith('plugin:') ? c.app.slice('plugin:'.length) : null);

const columns = (onEdit: (c: AppCredential) => void): ColumnDef<AppCredential>[] => [
  { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />, cell: ({ row }) => <span className="font-medium">{row.original.name}</span> },
  {
    id: 'app',
    accessorFn: (c) => c.appName,
    header: ({ column }) => <DataTableColumnHeader column={column} title="App" />,
    cell: ({ row }) => (
      <Link href={`/integrations/apps/${encodeURIComponent(row.original.app)}`} className="underline-offset-4 hover:underline">
        {row.original.appName}
      </Link>
    ),
  },
  {
    accessorKey: 'type',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />,
    cell: ({ row }) => <Badge variant={row.original.type === 'own' ? 'secondary' : 'default'}>{row.original.type === 'own' ? 'Your own app' : 'Ops AI’s app'}</Badge>,
  },
  {
    id: 'permissions',
    accessorFn: (c) => c.permissions.join(' '),
    header: ({ column }) => <DataTableColumnHeader column={column} title="Permissions" />,
    // A count, as the Credentials frame; the permissions themselves on hover.
    cell: ({ row }) => <span className="tabular-nums" title={row.original.permissions.join(' ')}>{row.original.permissions.length}</span>,
  },
  { accessorKey: 'accounts', header: ({ column }) => <DataTableColumnHeader column={column} title="Accounts" />, cell: ({ row }) => <span className="tabular-nums">{row.original.accounts}</span> },
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <Badge variant="outline" data-status={row.original.status}>{STATUS[row.original.status]}</Badge> },
  { accessorKey: 'created', header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />, cell: ({ row }) => <span className="text-sm text-muted-foreground">{shortDate(row.original.created)}</span> },
  {
    id: 'actions',
    header: () => null,
    // Only the team's own client has a secret to replace; Ops AI's app is the platform's.
    cell: ({ row }) =>
      row.original.type === 'own' && pluginOf(row.original) ? (
        <Button size="sm" variant="ghost" onClick={() => onEdit(row.original)} data-testid={`app-credential-edit-${row.original.id}`}>
          Edit
        </Button>
      ) : null,
  },
];

/**
 * App credentials (U4): the OAuth clients the team's apps sign in with, Ops AI's own app or the team's, from
 * GET /v1/app-credentials. Edit replaces the team's client secret (PUT /v1/plugins/{id}/app-secret), sealed on save.
 */
export function AppCredentialsPanel() {
  const creds = useAppCredentials();
  const [editing, setEditing] = React.useState<AppCredential | null>(null);
  const cols = React.useMemo(() => columns(setEditing), []);
  // A first answer that failed shows the error with Retry at once, not a skeleton while the retries run.
  if (!creds.data && (creds.isError || creds.failureCount > 0)) return <QueryError what="the app credentials" error={creds.error ?? creds.failureReason} onRetry={() => creds.refetch()} retrying={creds.isFetching} />;
  if (creds.isPending) return <PageSkeleton statCards={0} tableRows={4} />;
  return (
    <div className="flex flex-col gap-4" data-testid="app-credentials-panel">
      <DataTableWithViews
        columns={cols}
        data={creds.data}
        getRowId={(c) => c.id}
        searchColumn="name"
        searchPlaceholder="Search app credentials…"
        hideViewSwitcher
        emptyState={<ListEmpty icon={KeyRound} noun="app credentials" filtered={false} description="No app credentials yet. Connecting an app that signs in uses Ops AI’s app; use your own on the app’s Settings." />}
      />
      <EditSecretDialog credential={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

function EditSecretDialog({ credential, onClose }: { credential: AppCredential | null; onClose: () => void }) {
  const set = useSetAppSecret();
  const [secret, setSecret] = React.useState('');
  React.useEffect(() => {
    setSecret('');
  }, [credential]);
  return (
    <DialogShell
      open={!!credential}
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Replace the client secret of ${credential?.name ?? 'this app'}`}
      description="Sealed on save and never shown again. People stay connected."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={set.isPending}
            disabled={!secret.trim()}
            onClick={() =>
              credential &&
              pluginOf(credential) &&
              set.mutate(
                { path: { plugin_id: pluginOf(credential)! }, body: { clientSecret: secret.trim() } },
                { onSuccess: () => (toast.success(`Saved the client secret of ${credential.name}`), onClose()), onError: (e) => toast.error('Couldn’t save the client secret', { description: e.message }) },
              )
            }
            data-testid="app-credential-save"
          >
            Save
          </LoadingButton>
        </>
      }
    >
      <FormField id="app-credential-secret" label="Client secret">
        <Input id="app-credential-secret" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="Sealed on save" />
      </FormField>
    </DialogShell>
  );
}
