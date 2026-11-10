'use client';

import * as React from 'react';
import type { ColumnDef, ColumnFiltersState } from '@tanstack/react-table';
import Link from 'next/link';
import { ExternalLink, MoreVertical, Plug, Plus, RefreshCw, TriangleAlert } from 'lucide-react';
import { toast } from 'sonner';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
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
import { initials } from '@/lib/format';
import { accountOwnerWords } from '@/lib/app-state';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));


/** Who may run tools as the row: the team, one person, or each person with their own. */
const whoCan = (a: ConfigAccount) => (a.owner.kind === 'team' ? 'Team' : a.owner.kind === 'person' ? `Only ${a.owner.name}` : 'Each person');
/** What the row is shown as: whoever signed in, else the account's name. */
const shownAs = (a: ConfigAccount) => a.account ?? a.name;

/**
 * The app's Accounts tab: every account of the team that signs in to the app, in one table, with what each points at,
 * its state and only the actions the API offers per row. Add account, on the table's toolbar, is the one way to add
 * one, for whoever manages the team's apps; it is shown disabled with its reason while the app cannot sign one in. A
 * member sees the team's accounts and a count of their own sign-ins, which live on Connectors › Mine.
 * `config` opens it filtered to one auth config (from that config's account count).
 */
// What tells the account apart from the app's others (its org, its server, who signed in), as the API builds it.
const pointsAt = (a: ConfigAccount) => (a.identity ?? []).map((e) => e.shown).join(' · ');

export function AccountsTab({
  app,
  config,
  onConnect,
  addBlocked,
  onSignIn,
}: {
  app: AppPage;
  config?: string | null;
  /** Add account; absent for someone who does not manage the team's apps. */
  onConnect?: () => void;
  /** Why Add account cannot sign one in yet (lib/app-state.ts addAccountBlocked); null when it can. */
  addBlocked?: string | null;
  onSignIn: (account: 'self' | 'team', accountId: string) => void;
}) {
  const rows = app.accounts ?? [];
  const configs = app.authConfigs ?? [];
  const seesConfigs = Boolean(app.card.mayManage);
  const name = app.card.name;
  // Read through a ref so the columns keep one identity: new column functions remount every cell, which closes an open
  // row menu whenever the page above re-renders.
  const latest = React.useRef({ app, configs, onSignIn });
  latest.current = { app, configs, onSignIn };
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
              {pointsAt(a) && (
                <span className="truncate text-xs text-muted-foreground" title={(a.identity ?? []).map((e) => `${e.label}: ${e.value}`).join('\n')} data-testid={`account-org-${a.name}`}>
                  {pointsAt(a)}
                </span>
              )}
              {a.samePlaceAs && (
                <span className="flex items-center gap-1 text-xs text-warning-text" data-testid={`account-same-place-${a.name}`}>
                  <TriangleAlert className="size-3" />
                  {`Points at the same place as ${a.samePlaceAs}`}
                </span>
              )}
            </span>
          </span>
        ),
      },
      // Auth configs are shown only to whoever manages the team's apps; the API names none to anyone else.
      ...(seesConfigs
        ? ([
            {
              id: 'config',
              accessorFn: (a) => a.configName ?? '—',
              header: ({ column }) => <DataTableColumnHeader column={column} title="Auth config" />,
              meta: { kind: 'status' },
              cell: ({ row }) => <span className="whitespace-nowrap text-sm">{row.original.configName ?? '—'}</span>,
              filterFn: facetFilterFn,
            },
          ] as ColumnDef<ConfigAccount>[])
        : []),
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
        cell: ({ row: { original: a } }) => (
          <StateCell account={a} perPerson={latest.current.app.card.ownSignIn != null} onSignIn={(as, id) => latest.current.onSignIn(as, id)} />
        ),
        filterFn: facetFilterFn,
      },
      {
        id: 'actions',
        enableHiding: false,
        cell: ({ row: { original: a } }) => (
          <StopRowClick>
            <AccountActions
              app={latest.current.app}
              account={a}
              moveTo={latest.current.configs.filter((c) => c.id !== a.configId && c.type !== 'account')}
              onSignIn={(as, id) => latest.current.onSignIn(as, id)}
            />
          </StopRowClick>
        ),
      },
    ],
    [seesConfigs],
  );
  const facet = (id: 'config' | 'who' | 'run' | 'state', title: string, values: string[]) => ({
    column: id,
    title,
    options: [...new Set(values)].map((v) => ({ label: v, value: v })),
  });
  const signIns = app.me?.signIns ?? 0;
  const add = onConnect && (
    // Its own row below the search on a phone, beside it from sm up, so the search keeps its width.
    <div className="w-full sm:w-auto">
      {addBlocked ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span tabIndex={0} className="inline-flex w-full sm:w-auto" data-testid="app-add-account-blocked">
              <Button size="sm" className="w-full sm:w-auto" disabled aria-describedby="app-add-account-why" data-testid="app-add-account">
                <Plus />
                Add account
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent id="app-add-account-why">{addBlocked}</TooltipContent>
        </Tooltip>
      ) : (
        <Button size="sm" className="w-full sm:w-auto" onClick={onConnect} data-testid="app-add-account">
          <Plus />
          Add account
        </Button>
      )}
    </div>
  );
  return (
    <>
    <DataTableWithViews
      key={config ?? 'all'}
      columns={columns}
      data={rows}
      getRowId={(a) => a.rowId}
      searchColumn="signsInAs"
      searchPlaceholder="Search accounts…"
      hideViewSwitcher
      toolbarExtra={add || undefined}
      initialColumnFilters={filtered}
      filters={[
        ...(seesConfigs ? [facet('config', 'Auth config', rows.map((a) => a.configName ?? '—'))] : []),
        facet('who', 'Who can use it', rows.map((a) => (a.owner.kind === 'team' ? 'Team' : 'Personal'))),
        facet('run', 'Test or live', rows.map((a) => (a.sandbox ? 'Test' : 'Live'))),
        facet('state', 'State', rows.map((a) => STATE[a.state].label)),
      ]}
      emptyState={
        <EmptyState
          icon={Plug}
          title={`No account signs in to ${name} yet`}
          description={onConnect ? 'Add one. Ops AI’s app signs in without an auth config where the app allows it.' : 'Someone who manages the team’s apps adds the first one.'}
          action={onConnect && !addBlocked ? { label: 'Add account', onClick: onConnect } : undefined}
          testId="app-accounts-empty"
        />
      }
    />
    {!seesConfigs && signIns > 0 && (
      <p className="text-sm text-muted-foreground" data-testid="app-accounts-mine">
        {`You are signed in on ${signIns} ${signIns === 1 ? 'account' : 'accounts'} of ${name}. `}
        <Link href="/integrations/my-accounts" className="underline underline-offset-4">
          Your own accounts are on Connectors › Mine
        </Link>
      </p>
    )}
    </>
  );
}

/** The row's state, and the one action that fixes a broken sign-in, when the API offers it on the row. */
function StateCell({
  account: a,
  onSignIn,
  perPerson,
}: {
  account: ConfigAccount;
  onSignIn: (account: 'self' | 'team', accountId: string) => void;
  /** Each person signs in to the app, so the page's badge is the person's and a team row says it is the team's. */
  perPerson: boolean;
}) {
  const as = a.kind === 'person' || a.owner.kind === 'each' ? 'self' : 'team';
  // A test result counts only while the account is signed in; an account signed out since has just the one state.
  const failed = a.state === 'connected' && a.test?.status === 'failed' ? a.test.message || 'no reason given' : null;
  const can = (x: NonNullable<ConfigAccount['actions']>[number]) => (a.actions ?? []).includes(x);
  const owner = perPerson ? accountOwnerWords(a.owner.kind) : null;
  return (
    <span className="flex flex-col gap-1">
      <span className="flex flex-wrap items-center gap-2">
        {/* The team's account, said so where the page's own badge is the person's (lib/app-state.ts). */}
        {owner && <span className="text-xs text-muted-foreground">{owner}:</span>}
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
            <DropdownMenuItem key={m.label} onClick={m.onClick} className={m.destructive ? 'text-destructive-text' : undefined} data-testid={`account-action-${m.label}-${a.name}`}>
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
