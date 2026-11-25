'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { CircleCheck, CircleX, Clock, Plug, Plus, PlugZap } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { CardDescription } from '@/components/ui/card';
import { APP_CARD_GRID, AppCard } from '@/components/connections/app-card';
import { useCan } from '@/hooks/me-queries';
import { type AppFilters, type AppView, type SystemCard, useSystems } from '@/hooks/systems-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { initials, plural } from '@/lib/format';

import type { ConnectMode } from './connect-system-dialog';
import { appPageHref } from '@/lib/app-links';
import { appStateFor } from '@/lib/app-state';
import { APP_STATE_LOOK, AppStateBadge } from '@/components/connections/app-state-badge';
import { AddAuthConfigButton, TurnOnButton } from '@/components/connections/app-actions';
import { AppsTabs } from '@/components/connections/apps-tabs';
import { signInChoiceWords } from '@/lib/login-words';

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

/** How people sign in to an app, in the words of its Turn on window. */
const SIGN_IN_WORDS: Record<NonNullable<SystemCard['signIn']>, string> = {
  team: signInChoiceWords('team'),
  person: signInChoiceWords('person'),
  person_or_team: signInChoiceWords('person_or_team'),
};

/**
 * An app's sign-in health: its people's own sign-ins that work, ended and failed, counted by the server. An app the
 * team signs in to with one shared login has none.
 */
function SignInHealth({ id, counts }: { id: string; counts?: SystemCard['signIns'] }) {
  const parts = [
    { n: counts?.connected ?? 0, label: 'connected', icon: CircleCheck, className: 'text-success-text' },
    { n: counts?.expired ?? 0, label: 'ended', icon: Clock, className: 'text-warning-text' },
    { n: counts?.refused ?? 0, label: 'couldn’t connect', icon: CircleX, className: 'text-destructive-text' },
  ].filter((p) => p.n > 0);
  if (!parts.length) return <span className="text-sm text-muted-foreground" data-testid={`app-${id}-sign-ins`}>No sign-ins</span>;
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" data-testid={`app-${id}-sign-ins`}>
      {parts.map(({ n, label, icon: Icon, className }) => (
        <span key={label} className="inline-flex items-center gap-1 whitespace-nowrap tabular-nums">
          <Icon className={`size-4 ${className}`} aria-hidden />
          {n} {label}
        </span>
      ))}
    </span>
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
          <div className="text-xs text-muted-foreground">
            {plural(row.original.toolsCount, 'tool')}
            {row.original.category ? ` · ${row.original.category}` : ''}
          </div>
        </div>
      </div>
    ),
    enableHiding: false,
  },
  // Only the Category filter reads this column; the category shows under the app's name.
  { accessorKey: 'category', header: 'Category', enableSorting: false, filterFn: facetFilterFn, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.category}</span> },
  {
    id: 'signIn',
    enableSorting: false,
    header: 'How people sign in',
    cell: ({ row }) => <span className="whitespace-nowrap text-sm">{row.original.signIn ? SIGN_IN_WORDS[row.original.signIn] : '–'}</span>,
  },
  {
    id: 'signIns',
    enableSorting: false,
    header: 'Sign-ins',
    cell: ({ row }) => <SignInHealth id={row.original.id} counts={row.original.signIns} />,
  },
  {
    accessorKey: 'appState',
    enableSorting: false,
    filterFn: facetFilterFn,
    header: ({ column }) => <DataTableColumnHeader column={column} title="State" />,
    cell: ({ row }) =>
      row.original.appState === 'connected' ? (
        <span className="whitespace-nowrap text-sm">Connected · {plural(row.original.accountsCount, 'account')}</span>
      ) : (
        <AppStateBadge card={row.original} />
      ),
  },
  // Only the Kind filter reads this column; the server filters on it.
  { accessorKey: 'kind', enableSorting: false, filterFn: facetFilterFn, header: 'Kind', cell: ({ row }) => <span className="text-muted-foreground">{row.original.kindLabel}</span> },
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
 * The tabs (All, Connected, Available) and the State, Category and Kind filters are sent to the route, which counts
 * each tab and facet and lists connected apps first.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
  // Adding an app is managing the team's apps; a person who may not is offered no button, and each card says whom to ask.
  const mayAdd = useCan('connections', 'manage') === true;
  const router = useRouter();
  const list = useListParams<AppFilters>('name', 20);
  const [view, setView] = React.useState<AppView>('all');
  const systems = useSystems({ page: list.params.page, pageSize: list.params.pageSize, search: list.params.search, view, filters: list.params.filters });
  const counts = systems.data?.viewCounts;
  const facets = systems.data?.facets ?? {};
  const facetOptions = (key: string, label: (v: string) => string) =>
    Object.entries(facets[key] ?? {}).map(([value, count]) => ({ value, label: label(value), count }));
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
      description="Team setup: turn on the apps your agents and workflows use, choose how people sign in, and see whose sign-ins need attention."
      tabs={<AppsTabs />}
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
        <div data-testid="systems-grid" className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="App views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}`, icon: Plug },
              { id: 'connected', label: `Connected · ${counts?.connected ?? 0}`, icon: CircleCheck },
              { id: 'available', label: `Available · ${counts?.available ?? 0}`, icon: PlugZap },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as AppView);
              list.reset();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <DataTableWithViews
            columns={cols}
            data={rows}
            getRowId={(r) => r.id}
            defaultView="table"
            gridClassName={APP_CARD_GRID}
            renderGridItem={(s) => <SystemAppCard system={s} onConnect={onConnect} />}
            searchColumn="name"
            searchPlaceholder="Search apps"
            initialColumnVisibility={{ kind: false, category: false }}
            filters={[
              { column: 'appState', title: 'State', options: facetOptions('appState', (v) => APP_STATE_LOOK[v as keyof typeof APP_STATE_LOOK]?.label ?? v) },
              { column: 'category', title: 'Category', options: facetOptions('category', (v) => v) },
              { column: 'kind', title: 'Kind', options: facetOptions('kind', (v) => v.charAt(0).toUpperCase() + v.slice(1)) },
            ]}
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
