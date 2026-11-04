'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { NewAppCredentialDialog } from '@/components/connections/new-app-credential-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { type AppCredential, useAppCredentials, useSetCredentialSecret } from '@/hooks/systems-queries';
import { shortDate } from '@/lib/format';

export const CREDENTIAL_STATUS: Record<AppCredential['status'], string> = { working: 'Working', not_tested: 'Not tested', failing: 'Failing' };
/** An app credential's page under Credentials. */
export const credentialHref = (id: string) => `/integrations/credentials/${encodeURIComponent(id)}`;

const columns = (onEdit: (c: AppCredential) => void): ColumnDef<AppCredential>[] => [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
    cell: ({ row }) => (
      <Link href={credentialHref(row.original.id)} className="font-medium underline-offset-4 hover:underline" data-testid={`app-credential-open-${row.original.id}`}>
        {row.original.name}
      </Link>
    ),
  },
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
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <Badge variant="outline" data-status={row.original.status}>{CREDENTIAL_STATUS[row.original.status]}</Badge> },
  { accessorKey: 'created', header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />, cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.created ? shortDate(row.original.created) : '—'}</span> },
  {
    id: 'actions',
    header: () => null,
    // Only the team's own client has a secret to replace; Ops AI's app is the platform's.
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
 * using it, from GET /v1/app-credentials. A row opens the credential's page; Edit replaces the team's own client
 * secret (PUT /v1/app-credentials/{id}/secret), sealed on save. Ops AI's app is the install's and has none here.
 */
export function AppCredentialsPanel() {
  const creds = useAppCredentials();
  const router = useRouter();
  const [editing, setEditing] = React.useState<AppCredential | null>(null);
  const [adding, setAdding] = React.useState(false);
  const cols = React.useMemo(() => columns(setEditing), []);
  // A first answer that failed shows the error with Retry at once, not a skeleton while the retries run.
  if (!creds.data && (creds.isError || creds.failureCount > 0)) return <QueryError what="the app credentials" error={creds.error ?? creds.failureReason} onRetry={() => creds.refetch()} retrying={creds.isFetching} />;
  if (creds.isPending) return <PageSkeleton statCards={0} tableRows={4} />;
  return (
    <div className="flex flex-col gap-4" data-testid="app-credentials-panel">
      {/* The list answers team admins only, so the window that adds to it is theirs too. */}
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setAdding(true)} data-testid="new-app-credential">
          <Plus />
          New app credential
        </Button>
      </div>
      <DataTableWithViews
        columns={cols}
        data={creds.data.map((c) => ({ ...c, onRowClick: () => router.push(credentialHref(c.id)), href: credentialHref(c.id), rowTestId: `app-credential-row-${c.id}` }))}
        getRowId={(c) => c.id}
        searchColumn="name"
        searchPlaceholder="Search app credentials…"
        hideViewSwitcher
        emptyState={<ListEmpty icon={KeyRound} noun="app credentials" filtered={false} description="No app credentials yet. Connecting an app that signs in uses Ops AI’s app; add your own with New app credential." />}
      />
      <EditSecretDialog credential={editing} onClose={() => setEditing(null)} />
      <NewAppCredentialDialog open={adding} onOpenChange={setAdding} />
    </div>
  );
}

/** Replaces the team's own client secret of an app credential; every account on it keeps it. */
export function EditSecretDialog({ credential, onClose }: { credential: Pick<AppCredential, 'id' | 'name'> | null; onClose: () => void }) {
  const set = useSetCredentialSecret();
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
              set.mutate(
                { path: { credential_id: credential.id }, body: { clientSecret: secret.trim() } },
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
