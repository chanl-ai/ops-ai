'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, CircleCheck, CircleAlert, Plug, Plus, TriangleAlert } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { type AppState, type SystemCard, useSystems } from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { plural } from '@/lib/format';

import type { ConnectMode } from './connect-system-dialog';

export type { ConnectMode };
type View = 'all' | 'connected' | 'available';

const STATE: Record<AppState, { label: string; className: string; icon?: typeof CircleCheck }> = {
  connected: { label: 'Connected', className: 'border-success/40 bg-success/10 text-success-text', icon: CircleCheck },
  test_failed: { label: 'Signed in, test failed', className: 'border-warning/40 bg-warning/10 text-warning-text', icon: TriangleAlert },
  needs_sign_in: { label: 'Needs sign-in', className: 'border-warning/40 bg-warning/10 text-warning-text', icon: CircleAlert },
  not_installed: { label: 'Not installed', className: 'text-muted-foreground' },
  removed: { label: 'No longer installed', className: 'border-destructive/40 bg-destructive/10 text-destructive', icon: CircleAlert },
};

/** The app's state as a badge, worded the same on its card and its page. */
export function AppStateBadge({ card, testId }: { card: SystemCard; testId?: string }) {
  if (!card.appState) return null;
  const shown = STATE[card.appState];
  const Icon = shown.icon;
  return (
    <Badge variant="outline" className={shown.className} data-testid={testId}>
      {Icon && <Icon />}
      {shown.label}
    </Badge>
  );
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** The app's page, where its accounts, tools, skills, sign-ins, runs and settings are; a built-in app's is the console
 * page that manages it (its knowledge bases, its mailboxes). */
export const appHref = (s: Pick<SystemCard, 'id' | 'href'>) => s.href ?? `/integrations/apps/${encodeURIComponent(s.id)}`;

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
function AppCard({ system, onConnect }: { system: SystemCard; onConnect: (s: SystemCard, mode: ConnectMode) => void }) {
  const state = system.appState;
  const failure = state === 'test_failed' ? (system.appStateReason ?? 'no reason given') : null;
  return (
    <Card className="relative h-full min-h-40 gap-3 transition-all hover:border-primary/40 hover:shadow-md" data-testid={`system-${system.id}`} data-state={state}>
      <CardHeader className="flex flex-row items-center gap-2.5 px-4">
        <Avatar className="size-9 rounded-md">
          {system.logo && <AvatarImage src={system.logo} alt="" />}
          <AvatarFallback className="rounded-md text-xs font-semibold">{initials(system.name)}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <CardTitle className="truncate text-base">
            {/* Stretched over the card, so the whole card opens the app's page. */}
            <Link href={appHref(system)} className="after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none" data-testid={`card-link-${system.id}`}>
              {system.name}
            </Link>
          </CardTitle>
          <p className="truncate text-xs text-muted-foreground">
            {plural(system.toolsCount, 'tool')}
            {system.kindLabel ? ` · ${system.kindLabel}` : ''}
          </p>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 px-4">
        {system.description && <CardDescription className="line-clamp-1">{system.description}</CardDescription>}
        {system.category && (
          <div>
            <Badge variant="secondary">{system.category}</Badge>
          </div>
        )}
        {state === 'removed' && (
          <p className="line-clamp-2 text-xs text-destructive" data-testid={`system-${system.id}-removed`}>
            {system.appStateReason}
          </p>
        )}
        {failure && (
          <p className="line-clamp-2 text-xs text-warning-text" data-testid={`system-${system.id}-test-failed`}>
            Signed in, but a test call failed: {failure}
          </p>
        )}
        <div className="mt-auto flex items-center justify-between gap-2">
          {state === 'connected' ? (
            <Badge variant="outline" className={STATE.connected.className} data-testid={`system-${system.id}-state`}>
              <CircleCheck />
              Connected · {plural(system.accountsCount, 'account')}
            </Badge>
          ) : (
            <AppStateBadge card={system} testId={`system-${system.id}-state`} />
          )}
          {state === 'connected' || state === 'removed' ? null : !system.mayManage ? (
            // Only a team admin connects an app; anyone else is told why rather than shown a dead button.
            <span className="text-xs text-muted-foreground" data-testid={`connect-${system.id}-why`}>
              A team admin connects it
            </span>
          ) : state === 'test_failed' ? (
            <Button size="sm" variant="outline" className="relative z-10" onClick={() => onConnect(system, 'reconnect')} data-testid={`reconnect-${system.id}`}>
              Reconnect
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="relative z-10" onClick={() => onConnect(system, 'connect')} data-testid={`connect-${system.id}`}>
              Connect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
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
          {row.original.description && <div className="max-w-md truncate text-xs text-muted-foreground">{row.original.description}</div>}
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
    cell: ({ row }) => {
      const s = row.original;
      if (!s.mayManage || s.appState === 'connected' || s.appState === 'removed') return null;
      const mode: ConnectMode = s.appState === 'test_failed' ? 'reconnect' : 'connect';
      return (
        <Button size="sm" variant="outline" onClick={(e) => (e.stopPropagation(), onConnect(s, mode))}>
          {mode === 'reconnect' ? 'Reconnect' : 'Connect'}
        </Button>
      );
    },
    enableHiding: false,
  },
];

/**
 * The apps catalog on the console's standard list: search, Category and State filters, the Connected and Available
 * views, and a grid of cards or a table. Read from GET /v1/apps, each card already joined; the list is one team's apps,
 * so the table filters the rows it holds.
 */
export function SystemsGrid({ onConnect, onNew }: { onConnect: (s: SystemCard, mode: ConnectMode) => void; onNew: () => void }) {
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
      title="Apps"
      description="Browse and connect the apps your agents and workflows use."
      contentClassName="flex flex-col gap-4"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setView('connected')} data-testid="connected-apps">
            Connected apps
            <ArrowRight />
          </Button>
          <Button size="sm" onClick={onNew} data-testid="connect-system">
            <Plus />
            Add custom app
          </Button>
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
              gridClassName="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3"
              renderGridItem={(s) => <AppCard system={s} onConnect={onConnect} />}
              searchColumn="name"
              searchPlaceholder="Search apps"
              filters={[
                { column: 'category', title: 'Category', options: categories.map((c) => ({ label: c, value: c })) },
                { column: 'appState', title: 'State', options: STATE_OPTIONS },
              ]}
              filterResetKey={filterResetKey}
              emptyState={
                <ListEmpty
                  icon={Plug}
                  noun="apps"
                  filtered={view !== 'all' || rows.length > 0}
                  onClear={() => (setView('all'), setFilterResetKey((k) => k + 1))}
                  createLabel="Add custom app"
                  onCreate={onNew}
                  description="Your platform admin installs apps; you can add your own app now."
                />
              }
            />
          </div>
        </>
      )}
    </PageLayout>
  );
}
