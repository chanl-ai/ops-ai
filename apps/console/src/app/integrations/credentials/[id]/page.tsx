'use client';

import * as React from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity, ExternalLink, KeyRound, Pencil, Trash2, UserRoundPlus } from 'lucide-react';
import { toast } from 'sonner';

import { secretShown } from '@/components/connections/credential-display';
import { CredentialDeleteDialog } from '@/components/connections/credential-delete-dialog';
import { CredentialEditDialog } from '@/components/connections/credential-edit-dialog';
import { ConnectWindow, connectsInWindow } from '@/components/connections/connect-window';
import { useSignInWindow } from '@/components/connections/sign-in';
import { appHref } from '@/components/connections/systems-grid';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { CopyButton } from '@/components/shared/copy-button';
import { FieldRow } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useStartCredentialCheck } from '@/hooks/connections-queries';
import { type AppCredentialDetail, useAppCredential, useConnectionKinds, useSignOutTeam, useStartSignIn, useSystems } from '@/hooks/systems-queries';
import { useTeam } from '@/hooks/use-team';
import type { Kinds } from '@/lib/connect-plan';
import { shortDate } from '@/lib/format';

type Account = AppCredentialDetail['accountsList'][number] & { onReconnect: (a: Account) => void; onDisconnect: (a: Account) => void; busy: string | null; team: string };

const STATE: Record<Account['state'], { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive' }> = {
  connected: { label: 'Connected', variant: 'secondary' },
  not_signed_in: { label: 'Not signed in', variant: 'outline' },
  expired: { label: 'Expired', variant: 'outline' },
  refused: { label: 'Refused', variant: 'destructive' },
  revoked: { label: 'Revoked', variant: 'destructive' },
};

const shared = (a: Account) => (a.signIn === 'team' ? a.team : a.signIn === 'person' ? 'Each person' : 'Each person, team as backup');

const COLUMNS: ColumnDef<Account>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Account" />,
    cell: ({ row }) => (
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{row.original.name}</span>
        {row.original.sandbox && <Badge variant="outline">Sandbox</Badge>}
      </span>
    ),
  },
  { accessorKey: 'id', header: ({ column }) => <DataTableColumnHeader column={column} title="Account ID" />, cell: ({ row }) => <code className="text-xs text-muted-foreground">{row.original.id}</code> },
  {
    accessorKey: 'state',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => (
      <Badge variant={STATE[row.original.state].variant} title={row.original.stateReason ?? undefined} data-status={row.original.state}>
        {STATE[row.original.state].label}
      </Badge>
    ),
  },
  { id: 'shared', accessorFn: shared, header: ({ column }) => <DataTableColumnHeader column={column} title="Shared with" />, cell: ({ row }) => shared(row.original) },
  {
    accessorKey: 'connectedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Connected" />,
    cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.connectedAt ? shortDate(row.original.connectedAt) : 'Not yet'}</span>,
  },
  {
    id: 'actions',
    header: () => null,
    // Reconnect signs the team account in again; Disconnect ends its sign-in and keeps the account.
    cell: ({ row }) => {
      const a = row.original;
      const connected = a.state === 'connected';
      return (
        <LoadingButton
          size="sm"
          variant="ghost"
          isLoading={a.busy === a.id}
          onClick={() => (connected ? a.onDisconnect(a) : a.onReconnect(a))}
          data-testid={`credential-account-${connected ? 'disconnect' : 'reconnect'}-${a.id}`}
        >
          {connected ? 'Disconnect' : 'Reconnect'}
        </LoadingButton>
      );
    },
  },
];

/**
 * One app credential (GET /v1/app-credentials/{id}): its app, client id, permissions and who made it, and the
 * accounts signing in with it, joined by the API, with Reconnect and Disconnect on each. Connect account opens the
 * Connect window on this credential; Test with my account signs in through it as the caller, on its first account.
 */
export default function AppCredentialPage() {
  const { id } = useParams<{ id: string }>();
  const q = useAppCredential(decodeURIComponent(id));
  const c = q.data;
  const systems = useSystems();
  const kinds = useConnectionKinds();
  const { team, teamId, teams, switchTeam } = useTeam();
  const router = useRouter();
  // A link to a credential names its team; the page opens in it when the person is in that team.
  const wanted = useSearchParams().get('team');
  React.useEffect(() => {
    if (wanted && wanted !== teamId && teams.some((t) => t.id === wanted)) switchTeam(wanted);
  }, [wanted, teamId, teams, switchTeam]);
  const card = (systems.data ?? []).find((s) => s.id === c?.app);
  const all = kinds.data as Kinds | undefined;
  const connects = Boolean(card && all && connectsInWindow(card, all));
  const [connecting, setConnecting] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [busy, setBusy] = React.useState<string | null>(null);
  const start = useStartSignIn();
  const signOut = useSignOutTeam();
  const startCheck = useStartCredentialCheck();
  const signIn = useSignInWindow({
    onConnected: (m) => {
      setBusy(null);
      toast.success(`Signed in through ${c?.name ?? 'the auth config'}`, { description: m.account ? `As ${m.account}.` : undefined });
      void q.refetch();
    },
    onFailed: (why) => {
      setBusy(null);
      toast.error('The sign-in did not pass', { description: why });
    },
    onClosed: () => {
      setBusy(null);
      toast.error('The window was closed', { description: 'Access was not allowed, so nothing changed. Press it again to try once more.' });
    },
  });
  if (q.isPending) return <RecordSkeleton />;
  const own = c?.type === 'own';
  const first = c?.accountsList[0];

  const reconnect = (a: Account) => {
    // Opened in the click, before any call: a window opened after an await is blocked as a pop-up.
    const w = signIn.open(c?.appName ?? 'the app', card?.logo);
    if (!w || !c) return;
    setBusy(a.id);
    const ref = { appId: c.app, accountId: a.id };
    start.mutate({ ...ref, account: 'team' }, { onSuccess: (s) => w.go(s, ref), onError: (e) => (w.fail(e.message), setBusy(null)) });
  };
  const disconnect = (a: Account) => {
    if (!c) return;
    setBusy(a.id);
    signOut.mutate(
      { appId: c.app, accountId: a.id },
      { onSuccess: () => (toast.success(`Disconnected ${a.name}`), void q.refetch()), onError: (e) => toast.error(`Couldn’t disconnect ${a.name}`, { description: e.message }), onSettled: () => setBusy(null) },
    );
  };
  const testMine = () => {
    const w = signIn.open(c?.appName ?? 'the app', card?.logo);
    if (!w || !c || !first) return;
    setBusy('check');
    const ref = { appId: c.app, accountId: first.id };
    startCheck.mutate(ref, { onSuccess: (s) => w.go(s, ref), onError: (e) => (w.fail(e.message), setBusy(null)) });
  };

  const rows: Account[] = (c?.accountsList ?? []).map((a) => ({ ...a, onReconnect: reconnect, onDisconnect: disconnect, busy, team: team?.name ?? 'The team' }));
  return (
    <PageLayout
      icon={KeyRound}
      title={c?.name ?? 'Auth config'}
      description={c ? `${c.appName} · ${own ? 'Your own app' : 'Ops AI’s app'}` : undefined}
      backHref="/integrations/credentials"
      actions={
        c ? (
          <span className="flex flex-wrap gap-2">
            <LoadingButton variant="outline" isLoading={busy === 'check'} disabled={!first} title={first ? undefined : 'Connect an account first'} onClick={testMine} data-testid="credential-test">
              <Activity />
              Test with my account
            </LoadingButton>
            {connects && (
              <Button onClick={() => setConnecting(true)} data-testid="credential-connect">
                <ExternalLink />
                Connect account
              </Button>
            )}
          </span>
        ) : undefined
      }
    >
      {q.isError || !c ? (
        <QueryError what="this auth config" error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
      ) : (
        <RecordLayout
          rail={
            <AttributeCard
              title="Auth config"
              icon={KeyRound}
              testId="credential-details"
              action={
                own ? (
                  <span className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(true)} data-testid="credential-edit">
                      <Pencil />
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setDeleting(true)} data-testid="credential-delete">
                      <Trash2 />
                      Delete
                    </Button>
                  </span>
                ) : undefined
              }
            >
              <FieldRow label="App" value={c.appName} href={card ? appHref(card) : undefined} />
              <FieldRow label="Type" value={own ? 'Your own app' : 'Ops AI’s app'} />
              <FieldRow label="Client ID" value={c.clientId ?? (own ? undefined : 'Kept by the install')} mono={Boolean(c.clientId)} adornment={c.clientId ? <CopyButton text={c.clientId} size="icon" className="size-6" /> : undefined} testId="credential-client-id" />
              {own && <FieldRow label="Client secret" value={secretShown(c)} mono={Boolean(c.secretEnds)} testId="credential-secret" />}
              {(c.fields ?? []).map((f) => (
                <FieldRow key={f.name} label={f.label} value={(c.settings ?? {})[f.name] ? String((c.settings ?? {})[f.name]) : 'Not set'} mono={Boolean((c.settings ?? {})[f.name])} wrap testId={`credential-setting-${f.name}`} />
              ))}
              <FieldRow label="Status" value={{ working: 'Working', not_tested: 'Not tested', failing: 'Failing' }[c.status]} />
              <FieldRow label="Made by" value={c.createdBy ?? undefined} />
              <FieldRow label="Created" value={c.created ? shortDate(c.created) : undefined} />
              {own && c.redirectUri && <FieldRow label="Return address" value={c.redirectUri} mono wrap />}
              <div className="flex flex-col gap-1.5 pt-3" data-testid="credential-permissions">
                <span className="text-xs font-medium text-muted-foreground uppercase">Permissions</span>
                {c.permissions.length ? (
                  <span className="flex flex-wrap gap-1.5">
                    {c.permissions.map((p) => (
                      <Badge key={p.id} variant="outline" title={p.id}>
                        {p.label}
                      </Badge>
                    ))}
                  </span>
                ) : (
                  <span className="text-sm text-muted-foreground">All the app offers</span>
                )}
              </div>
            </AttributeCard>
          }
        >
          <Section title="Connected accounts" description="The accounts signing in with this auth config." flush>
            <div className="p-2" data-testid="credential-accounts">
              <DataTableWithViews
                columns={COLUMNS}
                data={rows}
                getRowId={(a) => a.id}
                searchColumn="name"
                searchPlaceholder="Search accounts…"
                hideViewSwitcher
                emptyState={
                  <ListEmpty
                    icon={UserRoundPlus}
                    noun="accounts"
                    filtered={false}
                    description={connects ? 'No accounts connected yet. Connect an account to use this app’s tools.' : 'No accounts connected yet.'}
                  />
                }
              />
            </div>
          </Section>
        </RecordLayout>
      )}
      {connecting && card && all && (
        <ConnectWindow
          card={card}
          kinds={all}
          another={Boolean(card.connectionId)}
          credential={own ? c?.id : null}
          open
          onOpenChange={(o) => !o && (setConnecting(false), void q.refetch())}
        />
      )}
      <CredentialEditDialog credentialId={editing && c ? c.id : null} onClose={() => (setEditing(false), void q.refetch())} />
      <CredentialDeleteDialog
        credential={deleting && c ? c : null}
        platform={Boolean(card?.managedClient)}
        onOpenChange={(o) => !o && setDeleting(false)}
        onDeleted={() => router.push('/integrations/credentials')}
      />
    </PageLayout>
  );
}
