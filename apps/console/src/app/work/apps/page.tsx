'use client';

import * as React from 'react';
import type { LegacyColumnDef as ColumnDef } from '@tanstack/react-table/legacy';
import { Plug, UserRound } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { Badge } from '@/components/ui/badge';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { APP_CARD_GRID, AppCard } from '@/components/connections/app-card';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import { CouldntConnect, MyAppAction, MyAppActions, MyAppMenu, NO_ACCOUNT, inChatWords, signInEnded, type MyAppControls } from '@/components/connections/my-app-actions';
import { type MyConnector, useMyConnectors } from '@/hooks/connections-queries';
import { useCan } from '@/hooks/me-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { ENDED_BY_AN_ADMIN, labelFor } from '@/lib/app-state';
import { plural, shortDate } from '@/lib/format';
import { myAppHref } from '@/lib/app-links';
import { MY_APPS } from '@/lib/nav';

/** Whom it signs in as: the primary account, with the other connected ones as a count. */
function SignedInAs({ c }: { c: MyConnector }) {
  if (c.appGroup === 'needs_you' && !signInEnded(c))
    return (
      <span className="text-sm text-muted-foreground" data-testid={`connector-missing-${c.appId}`}>
        {NO_ACCOUNT}
      </span>
    );
  const more = c.accountCount - 1;
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm">
      <span className="truncate">{signInEnded(c) ? `Was ${c.account ?? 'your account'}` : (c.account ?? 'Your account')}</span>
      {more > 0 && (
        <Badge variant="outline" data-testid={`connector-more-${c.appId}`}>
          +{plural(more, 'account')}
        </Badge>
      )}
    </span>
  );
}

/**
 * One app as a card: logo and name, what it can do as the person, whom it signs in as, its state and its one action.
 * The card opens the app's own page; on a phone the cards stack, so the action stays on screen.
 */
function AppsCard({ c, controls }: { c: MyConnector; controls: MyAppControls }) {
  return (
    <AppCard
      testId={`connector-${c.appId}`}
      state={c.appState}
      name={c.name}
      logo={c.logo}
      href={myAppHref(c.appId)}
      linkTestId={`connector-open-${c.appId}`}
      footState={<AppStateBadge card={c} manages={c.mayManage} testId={`connector-state-${c.appId}`} />}
      action={c.appGroup === 'on' ? <MyAppMenu c={c} controls={controls} /> : <MyAppAction c={c} controls={controls} />}
    >
      <p className="text-sm text-muted-foreground" data-testid={`connector-can-do-${c.appId}`}>
        {c.canDo}
      </p>
      <CouldntConnect appId={c.appId} why={controls.failed[c.appId]} />
      {c.appStateReason === ENDED_BY_AN_ADMIN && (
        <p className="text-sm text-warning-text" data-testid={`connector-ended-${c.appId}`}>
          Ended by an admin. Connect again to go on.
        </p>
      )}
      {/* An app the team sets up first has nothing of the person's to show: its state and one action say it all. */}
      {c.appGroup !== 'needs_admin' && (
        <>
          <div className="text-sm" data-testid={`connector-signed-in-${c.appId}`}>
            <SignedInAs c={c} />
          </div>
          <p className="text-xs text-muted-foreground">{c.appGroup === 'on' && c.since ? `${inChatWords(c)} · since ${shortDate(c.since)}` : inChatWords(c)}</p>
        </>
      )}
    </AppCard>
  );
}

/** What a person with no apps yet reads: what apps are here, what connecting does, and who turns them on. */
function NoApps() {
  const manages = useCan('connections', 'manage');
  return (
    <EmptyState
      icon={Plug}
      title="No apps to connect yet"
      description="Apps are the tools your team uses, such as a CRM or a ticket system. When your team turns one on, connect your own account here and chat and your agents can work in it as you. Until then, ask in chat; the first tool that needs you will ask."
      action={manages ? { label: 'Set up the team’s apps', href: '/data/connectors' } : undefined}
      testId="connectors-empty"
    />
  );
}

/**
 * My apps (the sidebar's lead row, under New chat): one card per app that acts as the person, with what it can do as
 * them, whom it signs in as, its state and its one action. Rows, states and counts come joined from tools-service
 * (GET /v1/me/connections). The team's setup is Apps under Data, for admins.
 */
export default function MyAppsPage() {
  const { team } = useTeam();
  const mine = useMyConnectors();
  const columns: ColumnDef<MyConnector>[] = [
    { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="App" />, meta: { kind: 'name' } },
    { id: 'state', accessorFn: (c) => labelFor(c.appState, c.mayManage), header: ({ column }) => <DataTableColumnHeader column={column} title="State" />, filterFn: facetFilterFn },
  ];
  const rows = mine.data ?? [];
  const connected = rows.filter((c) => c.appGroup === 'on').length;

  return (
    <PageLayout
      icon={UserRound}
      title={MY_APPS}
      description={`Apps that act as you in chat and in agents working for you, in ${team?.name ?? 'this team'}. Sign in once per team; disconnect here any time.`}
    >
      <MyAppActions>
        {(controls) =>
          mine.isPending ? (
            <PageSkeleton statCards={0} tableRows={4} />
          ) : mine.isError ? (
            <QueryError what="your apps" onRetry={() => void mine.refetch()} retrying={mine.isFetching} error={mine.error} testId="connectors-error" />
          ) : (
            <div className="flex flex-col gap-2" data-testid="connectors">
              <DataTableWithViews
                columns={columns}
                data={rows}
                getRowId={(c) => c.appId}
                defaultView="grid"
                gridClassName={APP_CARD_GRID}
                renderGridItem={(c) => <AppsCard c={c} controls={controls} />}
                searchColumn="name"
                searchPlaceholder="Search apps…"
                hidePaginationOnOnePage
                rowNoun="app"
                hideViewSwitcher
                filters={[{ column: 'state', title: 'State', options: [...new Set(rows.map((c) => labelFor(c.appState, c.mayManage)))].map((v) => ({ label: v, value: v })) }]}
                emptyState={<NoApps />}
              />
              {rows.length > 0 && (
                <p className="text-xs text-muted-foreground" data-testid="connectors-count">
                  {plural(rows.length, 'app')} · {connected} connected
                </p>
              )}
            </div>
          )
        }
      </MyAppActions>
    </PageLayout>
  );
}
