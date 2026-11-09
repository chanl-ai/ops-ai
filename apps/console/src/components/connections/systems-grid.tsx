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
import { EmptyState } from '@/components/shared/empty-state';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { CardDescription } from '@/components/ui/card';
import { APP_CARD_GRID, AppCard } from '@/components/connections/app-card';
import { useCan } from '@/hooks/me-queries';
import { type AppState, type SystemCard, useSystems } from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { initials, plural } from '@/lib/format';

import type { ConnectMode } from './connect-system-dialog';
import { appPageHref } from '@/lib/app-links';
import { appStateFor } from '@/lib/app-state';
import { APP_STATE_LOOK, AppStateBadge } from '@/components/connections/app-state-badge';
import { AddAuthConfigButton, TurnOnButton } from '@/components/connections/app-actions';

export type { ConnectMode };
type View = 'all' | 'connected' | 'available';

// An account whose sign-in ended (expired, refused or revoked) is signed in again with Reconnect, not Connect.
const ENDED = new Set(['expired', 'refused', 'revoked']);


const STATE = APP_STATE_LOOK;


/**
 * The card's one next action, from its state (lib/app-state.ts): Turn on, Add an auth config, Connect, Reconnect, or
 * whom to ask. An account whose sign-in ended is signed in again with Reconnect.
 */
function NextAction({ card, onConnect }: { card: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const { action } = appStateFor(card.appState, Boolean(card.mayManage));
  if (action === 'ask_admin') return <AskAnAdmin testId={`connect-${card.id}-why`} />;
  if (action === 'add_auth_config') return <AddAuthConfigButton appId={card.id} testId={`add-auth-config-${card.id}`} />;
  if (action === 'turn_on') return <TurnOnButton card={card} variant="outline" onFirstTurnOn={() => onConnect(card, 'connect')} testId={`connect-${card.id}`} />;
  if (!card.mayManage || (action !== 'sign_in' && action !== 'reconnect')) return null;
  const again = action === 'reconnect' || (card.appState === 'needs_sign_in' && ENDED.has(String(card.state)));
  return (
    <Button size="sm" variant="outline" onClick={(e) => (e.stopPropagation(), onConnect(card, again ? 'reconnect' : 'connect'))} data-testid={`${again ? 'reconnect' : 'connect'}-${card.id}`}>
      {again ? 'Reconnect' : 'Connect'}
    </Button>
  );
}

/** The app's page, where its accounts, tools, skills, sign-ins, runs and settings are; a built-in app's is the console
 * page that manages it (its knowledge bases, its mailboxes). */
export const appHref = (s: Pick<SystemCard, 'id' | 'href'>) => s.href ?? appPageHref(s.id);

/**
 * Connected holds the apps that are signed in and work, or signed in with a failed test (a warning, still connected),
 * and a removed app, whose card says why its tools stopped. Turned on but not signed in is Needs sign-in, under
 * Available with the apps not turned on: the API's appState decides which.
 */
const CONNECTED: ReadonlySet<AppState> = new Set<AppState>(['connected', 'test_failed', 'removed']);
const isConnected = (card: SystemCard) => CONNECTED.has(card.appState);

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

const STATE_OPTIONS = (Object.keys(STATE) as AppState[]).map((value) => ({ label: STATE[value].label, value }));

const columns = (onConnect: (s: SystemCard, mode: ConnectMode) => void): ColumnDef<Row>[] => [
  {
    // Holds every searched field, so the table's search matches an app by its name, line or category.
    id: 'name',
    accessorFn: (s) => `${s.name} ${s.description ?? ''} ${s.category ?? ''}`,
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
  { accessorKey: 'category', header: ({ column }) => <DataTableColumnHeader column={column} title="Category" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.category}</span>, filterFn: facetFilterFn },
  {
    accessorKey: 'appState',
    header: ({ column }) => <DataTableColumnHeader column={column} title="State" />,
    cell: ({ row }) =>
      row.original.appState === 'connected' ? (
        <span className="whitespace-nowrap text-sm">Connected · {plural(row.original.accountsCount, 'account')}</span>
      ) : (
        <AppStateBadge card={row.original} />
      ),
    filterFn: facetFilterFn,
  },
  { accessorKey: 'toolsCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Tools" />, cell: ({ row }) => <span className="tabular-nums">{row.original.toolsCount}</span> },
  {
    id: 'actions',
    meta: { className: 'w-28 text-right' },
    cell: ({ row }) => <NextAction card={row.original} onConnect={onConnect} />,
    enableHiding: false,
  },
];

/**
 * The apps catalog on the console's standard list: search, Category and State filters, the Connected and Available
 * views, and a grid of cards or a table. Read from GET /v1/apps, each card already joined; the list is one team's apps,
 * so the table filters the rows it holds.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
  // Adding an app is managing the team's apps; a person who may not is offered no button, and each card says whom to ask.
  const mayAdd = useCan('connections', 'manage') === true;
  const router = useRouter();
  const systems = useSystems();
  const [view, setView] = React.useState<View>('all');
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const cols = React.useMemo(() => columns(onConnect), [onConnect]);
  const rows: Row[] = React.useMemo(
    () =>
      [...(systems.data ?? [])]
        .filter((s) => view === 'all' || (view === 'connected') === isConnected(s))
        // Connected apps first, then the installed plugins, then the apps a person added.
        .sort((a, b) => Number(isConnected(b)) - Number(isConnected(a)) || Number(b.kind === 'plugin') - Number(a.kind === 'plugin'))
        .map((app) => ({ ...app, href: appHref(app), onRowClick: (x: SystemCard) => router.push(appHref(x)) })),
    [systems.data, view, router],
  );
  const categories = [...new Set((systems.data ?? []).map((s) => s.category).filter((c): c is string => Boolean(c)))].sort();
  return (
    <PageLayout
      icon={Plug}
      title="Connectors"
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
      ) : systems.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : (
        <>
          <SavedViewTabs
            ariaLabel="App views"
            presets={[
              { id: 'all', label: 'All apps' },
              { id: 'connected', label: 'Connected' },
              { id: 'available', label: 'Available' },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => setView(id as View)}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <div data-testid="systems-grid" data-view={view}>
            <DataTableWithViews
              columns={cols}
              data={rows}
              getRowId={(r) => r.id}
              defaultView="grid"
              gridClassName={APP_CARD_GRID}
              renderGridItem={(s) => <SystemAppCard system={s} onConnect={onConnect} />}
              searchColumn="name"
              searchPlaceholder="Search apps"
              filters={[
                { column: 'category', title: 'Category', options: categories.map((c) => ({ label: c, value: c })) },
                { column: 'appState', title: 'State', options: STATE_OPTIONS },
              ]}
              filterResetKey={filterResetKey}
              emptyState={
                view === 'connected' && !(systems.data ?? []).some((s) => s.appState === 'connected') ? (
                  // The view itself empties the list when nothing is connected yet: that is said, not "No apps match".
                  <EmptyState
                    icon={Plug}
                    title="No app is connected yet"
                    description="Connect one from All apps; it shows here once it signs in."
                    action={{ label: 'All apps', onClick: () => setView('all') }}
                    testId="apps-none-connected"
                  />
                ) : (
                  <ListEmpty
                    icon={Plug}
                    noun="apps"
                    filtered={view !== 'all' || rows.length > 0}
                    onClear={() => (setView('all'), setFilterResetKey((k) => k + 1))}
                    createLabel={mayAdd ? 'Add custom app' : undefined}
                    onCreate={mayAdd ? onNew : undefined}
                    description={mayAdd ? 'Your platform admin installs apps; you can add your own app now.' : 'Your platform admin installs apps.'}
                  />
                )
              }
            />
          </div>
        </>
      )}
    </PageLayout>
  );
}
