'use client';

import * as React from 'react';
import type { ColumnDef, ColumnFiltersState } from '@tanstack/react-table';
import { ExternalLink, MoreVertical, Plug, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { RenameDialog } from '@/components/shared/rename-dialog';
import { MoveDialog, STATE, type AuthConfig, type ConfigAccount } from '@/components/connections/app-auth-configs';
import {
  type AppPage,
  useChangeAccount,
  useDeleteAccount,
  useMakeTeamDefault,
  usePinDefault,
  useSignOutMine,
  useSignOutTeam,
  useTestAccount,
} from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

const initials = (name: string) =>
  name
    .replace(/@.*/, '')
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** Who may run tools as the row: the team, one person, or each person with their own. */
const whoCan = (a: ConfigAccount) => (a.owner.kind === 'team' ? 'Team' : a.owner.kind === 'person' ? `Only ${a.owner.name}` : 'Each person');
/** What the row is shown as: whoever signed in, else the account's name. */
const shownAs = (a: ConfigAccount) => a.account ?? a.name;

/**
 * The app's Accounts tab: every account that signs in to the app and each person's own sign-in, in one table, with
 * the state and only the actions the API offers per row. Connect, in the page header, is the one way to add one.
 * `config` opens it filtered to one auth config (from that config's account count).
 */
export function AccountsTab({
  app,
  config,
  onConnect,
  onSignIn,
}: {
  app: AppPage;
  config?: string | null;
  onConnect?: () => void;
  onSignIn: (account: 'self' | 'team', accountId: string) => void;
}) {
  const rows = app.accounts ?? [];
  const configs = app.authConfigs ?? [];
  const name = app.card.name;
  const filtered: ColumnFiltersState = config ? [{ id: 'config', value: [configs.find((c) => c.id === config)?.name ?? config] }] : [];
  const columns = React.useMemo<ColumnDef<ConfigAccount>[]>(
    () => [
      {
        id: 'signsInAs',
        accessorFn: (a) => `${shownAs(a)} ${a.name}`,
        header: ({ column }) => <DataTableColumnHeader column={column} title="Signs in as" />,
        meta: { kind: 'name' },
        cell: ({ row: { original: a } }) => (
          <span className="flex min-w-0 items-center gap-3" data-testid={`account-${a.name}`}>
            <Avatar className="size-7">
              <AvatarFallback className="text-[10px] font-semibold">{initials(shownAs(a))}</AvatarFallback>
            </Avatar>
            <span className="flex min-w-0 flex-col">
              <span className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="truncate">{shownAs(a)}</span>
                {a.default && <Badge variant="secondary">Default</Badge>}
                {a.sandbox && (
                  <Badge variant="outline" data-testid={`account-sandbox-${a.name}`}>
                    Test
                  </Badge>
                )}
              </span>
              {shownAs(a) !== a.name && <span className="truncate text-xs text-muted-foreground">{a.name}</span>}
            </span>
          </span>
        ),
      },
      {
        id: 'config',
        accessorFn: (a) => a.configName ?? '—',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Auth config" />,
        meta: { kind: 'status' },
        cell: ({ row }) => <span className="whitespace-nowrap text-sm">{row.original.configName ?? '—'}</span>,
        filterFn: facetFilterFn,
      },
      {
        id: 'who',
        accessorFn: (a) => (a.owner.kind === 'team' ? 'Team' : 'Personal'),
        header: ({ column }) => <DataTableColumnHeader column={column} title="Who can use it" />,
        meta: { kind: 'status' },
        cell: ({ row }) => <span className="whitespace-nowrap text-sm">{whoCan(row.original)}</span>,
        filterFn: facetFilterFn,
      },
      {
        id: 'run',
        accessorFn: (a) => (a.sandbox ? 'Test' : 'Live'),
        header: ({ column }) => <DataTableColumnHeader column={column} title="Test or live" />,
        meta: { kind: 'status' },
        cell: ({ row }) => <span className="whitespace-nowrap text-sm">{row.original.sandbox ? 'Test' : 'Live'}</span>,
        filterFn: facetFilterFn,
      },
      {
        id: 'state',
        accessorFn: (a) => STATE[a.state].label,
        header: ({ column }) => <DataTableColumnHeader column={column} title="State" />,
        meta: { kind: 'status' },
        cell: ({ row: { original: a } }) => <StateCell account={a} onSignIn={onSignIn} />,
        filterFn: facetFilterFn,
      },
      {
        id: 'actions',
        enableHiding: false,
        cell: ({ row: { original: a } }) => (
          <StopRowClick>
            <AccountActions app={app} account={a} moveTo={configs.filter((c) => c.id !== a.configId && c.type !== 'account')} onSignIn={onSignIn} />
          </StopRowClick>
        ),
      },
    ],
    [app, configs, onSignIn],
  );
  const facet = (id: 'config' | 'who' | 'run' | 'state', title: string, values: string[]) => ({
    column: id,
    title,
    options: [...new Set(values)].map((v) => ({ label: v, value: v })),
  });
  return (
    <DataTableWithViews
      key={config ?? 'all'}
      columns={columns}
      data={rows}
      getRowId={(a) => a.rowId}
      searchColumn="signsInAs"
      searchPlaceholder="Search accounts…"
      hideViewSwitcher
      initialColumnFilters={filtered}
      filters={[
        facet('config', 'Auth config', rows.map((a) => a.configName ?? '—')),
        facet('who', 'Who can use it', rows.map((a) => (a.owner.kind === 'team' ? 'Team' : 'Personal'))),
        facet('run', 'Test or live', rows.map((a) => (a.sandbox ? 'Test' : 'Live'))),
        facet('state', 'State', rows.map((a) => STATE[a.state].label)),
      ]}
      emptyState={
        <EmptyState
          icon={Plug}
          title={`No account signs in to ${name} yet`}
          description={onConnect ? 'Connect one. Ops AI’s app works without any setup.' : 'An admin connects the first one.'}
          action={onConnect ? { label: 'Connect', onClick: onConnect } : undefined}
          testId="app-accounts-empty"
        />
      }
    />
  );
}

/** The row's state, and the one action that fixes a broken sign-in, when the API offers it on the row. */
function StateCell({ account: a, onSignIn }: { account: ConfigAccount; onSignIn: (account: 'self' | 'team', accountId: string) => void }) {
  const as = a.kind === 'person' || a.owner.kind === 'each' ? 'self' : 'team';
  const failed = a.test?.status === 'failed' ? a.test.message || 'no reason given' : null;
  const can = (x: NonNullable<ConfigAccount['actions']>[number]) => (a.actions ?? []).includes(x);
  return (
    <span className="flex flex-col gap-1">
      <span className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={STATE[a.state].className} data-testid={`account-state-${a.name}`} data-state={a.state}>
          {STATE[a.state].label}
        </Badge>
        {can('sign_in') && (
          <Button size="sm" variant="outline" onClick={() => onSignIn(as, a.id)} data-testid={`account-sign-in-${a.name}`}>
            <ExternalLink />
            Sign in
          </Button>
        )}
        {can('reconnect') && (a.state !== 'connected' || failed) && (
          <Button size="sm" variant="outline" onClick={() => onSignIn(as, a.id)} data-testid={`account-reconnect-${a.name}`}>
            <RefreshCw />
            Reconnect
          </Button>
        )}
      </span>
      {failed && (
        <span className="text-xs text-warning-text" data-testid={`account-test-failed-${a.name}`}>
          Signed in, but a test call failed: {failed}
        </span>
      )}
      {a.stateReason && a.state !== 'connected' && <span className="text-xs text-muted-foreground">{a.stateReason}</span>}
    </span>
  );
}

/** A row's menu: Test now, Rename, defaults, Move, Disconnect and Delete, each only where the API offers it. */
function AccountActions({
  app,
  account: a,
  moveTo,
  onSignIn,
}: {
  app: AppPage;
  account: ConfigAccount;
  moveTo: AuthConfig[];
  onSignIn: (account: 'self' | 'team', accountId: string) => void;
}) {
  const ref = { appId: app.card.id, accountId: a.id };
  const change = useChangeAccount();
  const remove = useDeleteAccount();
  const signOutTeam = useSignOutTeam();
  const signOutMine = useSignOutMine();
  const pin = usePinDefault();
  const teamDefault = useMakeTeamDefault();
  const test = useTestAccount();
  const [dialog, setDialog] = React.useState<'rename' | 'move' | 'delete' | null>(null);
  const can = (x: NonNullable<ConfigAccount['actions']>[number]) => (a.actions ?? []).includes(x);
  const own = a.kind === 'person' || a.owner.kind === 'each';
  const disconnect = () =>
    (own ? signOutMine.mutateAsync(a.id) : signOutTeam.mutateAsync(ref)).then(
      () => toast.success(`${shownAs(a)} is disconnected`),
      (e: unknown) => toast.error('Couldn’t disconnect', { description: message(e) }),
    );
  const menu = [
    a.state !== 'not_signed_in' &&
      (can('reconnect') || can('disconnect')) && {
        label: 'Test now',
        onClick: () =>
          test.mutate(
            { ...ref, account: own ? 'self' : 'team' },
            {
              onSuccess: (r) => {
                // What the test read, as one line: the status it answered, what it said, and whose sign-in it used.
                const h = r.health;
                const said = [h?.httpStatus ? `HTTP ${h.httpStatus}` : null, h?.status === 'ok' ? null : h?.message, `with ${own ? 'your own account' : 'the team account'}`].filter(Boolean).join(' · ');
                if (h?.status === 'ok') toast.success(`${shownAs(a)} works`, { description: said });
                else toast.error(`${shownAs(a)}’s test failed`, { description: said });
              },
              onError: (e) => toast.error('Couldn’t test it', { description: e.message }),
            },
          ),
      },
    can('reconnect') && a.state === 'connected' && { label: 'Reconnect', onClick: () => onSignIn(own ? 'self' : 'team', a.id) },
    can('rename') && a.kind === 'team' && { label: 'Rename', onClick: () => setDialog('rename') },
    can('make_team_default') && {
      label: 'Make the team’s default',
      onClick: () =>
        teamDefault.mutate(ref, {
          onSuccess: () => toast.success(`${shownAs(a)} is the team’s default`, { description: 'Calls that name no account use it.' }),
          onError: (e) => toast.error('Couldn’t make it the default', { description: e.message }),
        }),
    },
    can('make_default') && {
      label: 'Make my default',
      onClick: () => pin.mutate(ref, { onError: (e) => toast.error('Couldn’t make it your default', { description: e.message }) }),
    },
    can('move') && a.kind === 'team' && moveTo.length > 0 && { label: 'Move to another auth config', onClick: () => setDialog('move') },
    can('disconnect') && { label: 'Disconnect', onClick: () => void disconnect() },
    can('delete') && a.kind === 'team' && { label: 'Delete', onClick: () => setDialog('delete'), destructive: true },
  ].filter(Boolean) as { label: string; onClick: () => void; destructive?: boolean }[];
  if (!menu.length) return null;
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`${shownAs(a)} actions`}
            data-testid={`account-menu-${a.name}`}
            data-default={a.default && a.kind === 'team' ? 'true' : undefined}
            data-mine={a.mine && (a.kind === 'person' || a.owner.kind === 'each') ? 'true' : undefined}
          >
            <MoreVertical />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {menu.map((m) => (
            <DropdownMenuItem key={m.label} onClick={m.onClick} className={m.destructive ? 'text-destructive' : undefined} data-testid={`account-action-${m.label}-${a.name}`}>
              {m.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      {dialog === 'rename' && (
        <RenameDialog
          name={a.name}
          description="Steps and tools pick an account by this name."
          testId="account-rename"
          busy={change.isPending}
          onClose={() => setDialog(null)}
          onSave={(next) =>
            change.mutate(
              { ...ref, body: { revision: a.revision, name: next } },
              { onSuccess: () => (toast.success(`Renamed to ${next}`), setDialog(null)), onError: (e) => toast.error('Couldn’t rename it', { description: e.message }) },
            )
          }
        />
      )}
      {dialog === 'move' && (
        <MoveDialog
          account={a.name}
          to={moveTo}
          busy={change.isPending}
          onClose={() => setDialog(null)}
          onMove={(c) =>
            change.mutate(
              // Ops AI's own app is no credential: null puts the account on it.
              { ...ref, body: { revision: a.revision, credentialId: c.type === 'ops_ai' ? null : c.id } },
              {
                onSuccess: () => (toast.success(`${a.name} moved to ${c.name}`, { description: 'It signs in again with Reconnect.' }), setDialog(null)),
                onError: (e) => toast.error('Couldn’t move it', { description: e.message }),
              },
            )
          }
        />
      )}
      <DeleteDialog
        open={dialog === 'delete'}
        onOpenChange={(o) => !o && setDialog(null)}
        entityType="account"
        entityName={a.name}
        description={`Calls naming ${a.name} stop working. Its sign-in is ended.`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(ref);
            toast.success(`${a.name} is deleted`);
            setDialog(null);
          } catch (e) {
            toast.error('Couldn’t delete it', { description: message(e) });
          }
        }}
        testIdPrefix={`account-delete-${a.name}`}
      />
    </>
  );
}
