'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { CircleCheck, Plug, Plus } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { CardDescription } from '@/components/ui/card';
import { APP_CARD_GRID, AppCard } from '@/components/connections/app-card';
import { useCan } from '@/hooks/me-queries';
import { type SystemCard, useSystems } from '@/hooks/systems-queries';
import { useListParams } from '@/hooks/use-list-params';
import { initials, plural } from '@/lib/format';

import type { ConnectMode } from './connect-system-dialog';
import { appPageHref } from '@/lib/app-links';
import { appStateFor } from '@/lib/app-state';
import { APP_STATE_LOOK, AppStateBadge } from '@/components/connections/app-state-badge';
import { AddAuthConfigButton, TurnOnButton } from '@/components/connections/app-actions';

export type { ConnectMode };

// An account whose sign-in ended (expired, refused or revoked) is signed in again with Reconnect, not Connect.
const ENDED = new Set(['expired', 'refused', 'revoked']);


const STATE = APP_STATE_LOOK;


/**
 * The card's one next action, from its state (lib/app-state.ts): Turn on, Add an auth config, Connect, Reconnect, or
 * whom to ask. An account whose sign-in ended is signed in again with Reconnect.
 */
function NextAction({ card, onConnect }: { card: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const { action } = appStateFor(card.appState, card.appGroup, Boolean(card.mayManage));
  if (action === 'ask_admin') return <AskAnAdmin testId={`connect-${card.id}-why`} />;
  if (action === 'fix_auth_config')
    return (
      <Button size="sm" variant="outline" asChild data-testid={`fix-auth-config-${card.id}`}>
        <Link href={appPageHref(card.id, 'auth')} onClick={(e) => e.stopPropagation()}>
          Fix the auth config
        </Link>
      </Button>
    );
  if (action === 'add_auth_config') return <AddAuthConfigButton appId={card.id} testId={`add-auth-config-${card.id}`} />;
  if (action === 'turn_on') return <TurnOnButton card={card} variant="outline" onFirstTurnOn={() => onConnect(card, 'connect')} testId={`connect-${card.id}`} />;
  if (!card.mayManage || (action !== 'sign_in' && action !== 'reconnect')) return null;
  const again = action === 'reconnect' || (card.appState === 'needs_sign_in' && ENDED.has(String(card.state)));
  return (
    <Button size="sm" variant="outline" onClick={(e) => (e.stopPropagation(), onConnect(card, again ? 'reconnect' : 'connect'))} data-testid={`${again ? 'reconnect' : 'connect'}-${card.id}`}>
      {again ? 'Sign in' : 'Connect'}
    </Button>
  );
}

/** The app's page, where its accounts, tools, skills, sign-ins, runs and settings are; a built-in app's is the console
 * page that manages it (its knowledge bases, its mailboxes). */
export const appHref = (s: Pick<SystemCard, 'id' | 'href'>) => s.href ?? appPageHref(s.id);

/**
 * One app's card: logo, name, tools and how it signs in, one line, its category, its state and at most one action.
 * The whole card opens the app's page; Connect or Reconnect sits above that link. A connected card has no button and
 * names its accounts; a second account is added on the app's page.
 */
function SystemAppCard({ system, onConnect }: { system: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const state = system.appState;
  const failure = state === 'test_failed' ? (system.appStateReason ?? 'no reason given') : null;
  return (
    <AppCard
      testId={`system-${system.id}`}
      state={state}
      name={system.name}
      logo={system.logo}
      href={appHref(system)}
      linkTestId={`card-link-${system.id}`}
      subtitle={`${plural(system.toolsCount, 'tool')}${system.kindLabel ? ` · ${system.kindLabel}` : ''}`}
      footState={
        state === 'connected' ? (
          <Badge variant="outline" className={STATE.connected.className} data-testid={`system-${system.id}-state`}>
            <CircleCheck />
            Connected · {plural(system.accountsCount, 'account')}
          </Badge>
        ) : (
          <AppStateBadge card={system} testId={`system-${system.id}-state`} />
        )
      }
      action={<NextAction card={system} onConnect={onConnect} />}
    >
      {system.description && <CardDescription className="break-words line-clamp-none">{system.description}</CardDescription>}
      {system.category && (
        <div>
          <Badge variant="secondary">{system.category}</Badge>
        </div>
      )}
      {state === 'removed' && (
        <p className="line-clamp-2 text-xs text-destructive-text" data-testid={`system-${system.id}-removed`}>
          {system.appStateReason}
        </p>
      )}
      {failure && (
        <p className="text-xs text-warning-text break-words" data-testid={`system-${system.id}-test-failed`}>
          Signed in, but a test call failed: {failure}
        </p>
      )}
    </AppCard>
  );
}

type Row = SystemCard & { onRowClick: (s: SystemCard) => void; href: string };

const columns = (onConnect: (s: SystemCard, mode: ConnectMode) => void): ColumnDef<Row>[] => [
  {
    // The table's search box names this column; the text goes to the server, which matches the name and category.
    id: 'name',
    accessorFn: (s) => s.name,
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title="App" />,
    cell: ({ row }) => (
      <div className="flex min-w-56 items-center gap-3" data-testid={`app-row-${row.original.id}`}>
        <Avatar className="size-8 rounded-md">
          {row.original.logo && <AvatarImage src={row.original.logo} alt="" />}
          <AvatarFallback className="rounded-md text-xs font-semibold">{initials(row.original.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="truncate font-medium">{row.original.name}</div>
          {row.original.description && <div className="max-w-md text-xs text-muted-foreground break-words">{row.original.description}</div>}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'category', header: ({ column }) => <DataTableColumnHeader column={column} title="Category" />, enableSorting: false, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.category}</span> },
  {
    accessorKey: 'appState',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title="State" />,
    cell: ({ row }) =>
      row.original.appState === 'connected' ? (
        <span className="whitespace-nowrap text-sm">Connected · {plural(row.original.accountsCount, 'account')}</span>
      ) : (
        <AppStateBadge card={row.original} />
      ),
  },
  { accessorKey: 'toolsCount', enableSorting: false, header: ({ column }) => <DataTableColumnHeader column={column} title="Tools" />, cell: ({ row }) => <span className="tabular-nums">{row.original.toolsCount}</span> },
  {
    id: 'actions',
    meta: { className: 'w-28 text-right' },
    cell: ({ row }) => <NextAction card={row.original} onConnect={onConnect} />,
    enableHiding: false,
  },
];

/**
 * The apps catalog on the console's standard list: search and a grid of cards or a table. One page of the team's
 * apps is read from GET /v1/apps, each card already joined, searched and paged on the server (by name, then id).
 * That route takes no state, category or Connected filter yet, so the page offers none.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
  // Adding an app is managing the team's apps; a person who may not is offered no button, and each card says whom to ask.
  const mayAdd = useCan('connections', 'manage') === true;
  const router = useRouter();
  const list = useListParams<Record<string, never>>('name', 20);
  const systems = useSystems({ page: list.params.page, pageSize: list.params.pageSize, search: list.params.search });
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const cols = React.useMemo(() => columns(onConnect), [onConnect]);
  const rows: Row[] = React.useMemo(
    () => (systems.data?.data ?? []).map((app) => ({ ...app, href: appHref(app), onRowClick: (x: SystemCard) => router.push(appHref(x)) })),
    [systems.data, router],
  );
  return (
    <PageLayout
      icon={Plug}
      title="Apps"
      switcher
      description="Team setup: turn on the apps your agents and workflows use, and choose whose account their tools use."
      contentClassName="flex flex-col gap-4"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {mayAdd && (
            <Button size="sm" onClick={onNew} data-testid="connect-system">
              <Plus />
              Add custom app
            </Button>
          )}
        </div>
      }
    >
      {/* A first answer that failed shows the error with Retry at once, not a skeleton while the retries run. */}
      {!systems.data && (systems.isError || systems.failureCount > 0) ? (
        <QueryError what="your apps" error={systems.error ?? systems.failureReason} onRetry={() => systems.refetch()} retrying={systems.isFetching} />
      ) : systems.isPending || !systems.data ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : (
        <div data-testid="systems-grid">
          <DataTableWithViews
            columns={cols}
            data={rows}
            getRowId={(r) => r.id}
            defaultView="grid"
            gridClassName={APP_CARD_GRID}
            renderGridItem={(s) => <SystemAppCard system={s} onConnect={onConnect} />}
            searchColumn="name"
            searchPlaceholder="Search apps"
            onColumnFiltersChange={list.onColumnFiltersChange}
            filterResetKey={filterResetKey}
            serverPagination={{
              enabled: true,
              total: systems.data.pagination.total,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: systems.data.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: systems.isFetching && systems.isPlaceholderData,
            }}
            emptyState={
              <ListEmpty
                icon={Plug}
                noun="apps"
                filtered={list.isFiltered}
                onClear={() => setFilterResetKey((k) => k + 1)}
                createLabel={mayAdd ? 'Add custom app' : undefined}
                onCreate={mayAdd ? onNew : undefined}
                description={mayAdd ? 'Your platform admin installs apps; you can add your own app now.' : 'Your platform admin installs apps.'}
              />
            }
          />
        </div>
      )}
    </PageLayout>
  );
}
