'use client';

import * as React from 'react';
import type { LegacyColumnDef as ColumnDef } from '@tanstack/react-table/legacy';
import { CircleCheck, CircleX, Clock, Plug, Users } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { AppLogo } from '@/components/shared/app-logo';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, NoAccess, QueryError } from '@/components/shared/query-states';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/me-queries';
import { type AppPerson, type PeopleFilters, type PersonSignIn, useAppPeople, useEndSignIn } from '@/hooks/systems-queries';
import { useListParams } from '@/hooks/use-list-params';
import { initials, relativeTime } from '@/lib/format';

import { AppsTabs } from './apps-tabs';

const MANAGE = { area: 'connections', action: 'manage' } as const;
const ENDED_BY_ADMIN = 'ended_by_admin';

/** A sign-in's state in the words My apps uses, with how it looks. */
const STATE_WORDS: Record<PersonSignIn['state'], { label: string; className: string; icon: typeof CircleCheck }> = {
  connected: { label: 'Connected', className: 'border-success/40 bg-success/10 text-success-text', icon: CircleCheck },
  expired: { label: 'Sign-in ended', className: 'border-warning/40 bg-warning/10 text-warning-text', icon: Clock },
  refused: { label: 'Couldn’t connect', className: 'border-destructive/40 bg-destructive/10 text-destructive-text', icon: CircleX },
};

const lookOf = (s: PersonSignIn) =>
  s.state === 'refused' && s.refusedReason === ENDED_BY_ADMIN ? { ...STATE_WORDS.refused, label: 'Ended by an admin' } : STATE_WORDS[s.state];

/** The one line under a sign-in's state: when it was last used, what the system said, or who ended it. */
function signInLine(s: PersonSignIn): string {
  if (s.refusedReason === ENDED_BY_ADMIN) return `Ended by ${s.endedBy ?? 'an admin'}${s.refusedAt ? ` ${relativeTime(s.refusedAt)}` : ''}`;
  if (s.state === 'refused') return s.refusedReason ? `Refused: ${s.refusedReason}` : 'The app refused the sign-in';
  if (s.state === 'expired') return s.expiresAt ? `Ended ${relativeTime(s.expiresAt)}` : 'The sign-in ended';
  return s.lastUsedAt ? `Last used ${relativeTime(s.lastUsedAt)}` : 'Not used yet';
}

/** A count with its state's icon, or a dash for none, as the mock's columns read. */
function Count({ n, icon: Icon, className, testId }: { n: number; icon: typeof CircleCheck; className: string; testId: string }) {
  if (!n) return <span className="text-muted-foreground" data-testid={testId}>–</span>;
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums" data-testid={testId}>
      <Icon className={`size-4 ${className}`} aria-hidden />
      {n}
    </span>
  );
}

type Row = AppPerson & { onRowClick: () => void; rowTestId: string };

const columns: ColumnDef<Row>[] = [
  {
    id: 'name',
    accessorFn: (p) => p.name,
    enableSorting: false,
    enableHiding: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Person" />,
    cell: ({ row }) => (
      <div className="flex min-w-48 items-center gap-3">
        <Avatar className="size-8">
          <AvatarFallback className="text-xs font-semibold">{initials(row.original.name)}</AvatarFallback>
        </Avatar>
        <span className="truncate font-medium">{row.original.name}</span>
      </div>
    ),
  },
  {
    // Only the App filter reads this column; the server filters on it.
    id: 'app',
    accessorFn: (p) => p.apps.map((a) => a.appId).join(' '),
    enableSorting: false,
    header: 'Apps',
    cell: ({ row }) => (
      <div className="flex flex-wrap items-center gap-1">
        {row.original.apps.map((a) => (
          <AppLogo key={a.appId} name={a.name} logo={a.logo} title={a.name} />
        ))}
      </div>
    ),
  },
  { id: 'connected', header: 'Connected', cell: ({ row }) => <Count n={row.original.connected} icon={CircleCheck} className="text-success-text" testId={`person-${row.original.personId}-connected`} /> },
  {
    // The State filter reads this column; the server keeps the people with a sign-in in any state picked.
    id: 'state',
    accessorFn: (p) => p.expired,
    header: 'Sign-in ended',
    cell: ({ row }) => <Count n={row.original.expired} icon={Clock} className="text-warning-text" testId={`person-${row.original.personId}-expired`} />,
  },
  { id: 'refused', header: 'Couldn’t connect', cell: ({ row }) => <Count n={row.original.refused} icon={CircleX} className="text-destructive-text" testId={`person-${row.original.personId}-refused`} /> },
  {
    id: 'lastUsed',
    header: 'Last used',
    cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.lastUsedAt ? relativeTime(row.original.lastUsedAt) : 'Not yet'}</span>,
  },
];

/** One person's sign-ins in the sheet, each with its state and End sign-in; an ended one offers none. */
function PersonSheet({ person, onClose, navigation }: { person: AppPerson | null; onClose: () => void; navigation?: React.ComponentProps<typeof DetailSheet>['navigation'] }) {
  const end = useEndSignIn();
  const [ending, setEnding] = React.useState<PersonSignIn | null>(null);
  return (
    <>
      <DetailSheet
        open={person !== null}
        onOpenChange={(o) => !o && onClose()}
        title={person?.name ?? ''}
        description={person && person.name !== person.personId ? person.personId : undefined}
        navigation={navigation}
        scrollKey={person?.personId}
        testId="person-sheet"
        widthClass="sm:max-w-lg"
      >
        <ul className="flex flex-col divide-y" aria-label="Sign-ins">
          {(person?.signIns ?? []).map((s) => {
            const look = lookOf(s);
            const Icon = look.icon;
            const ended = s.refusedReason === ENDED_BY_ADMIN;
            return (
              <li key={`${s.accountId}`} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between" data-testid={`sign-in-${s.accountId}`}>
                <div className="flex min-w-0 items-start gap-3">
                  <AppLogo name={s.appName} logo={s.logo} className="size-8" />
                  <div className="min-w-0">
                    <div className="font-medium">{s.appName}</div>
                    {s.accountName !== s.appName && <div className="text-xs text-muted-foreground">{s.accountName}</div>}
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className={look.className} data-testid={`sign-in-${s.accountId}-state`}>
                        <Icon />
                        {look.label}
                      </Badge>
                      <span className="text-sm text-muted-foreground break-words">{signInLine(s)}</span>
                    </div>
                  </div>
                </div>
                {!ended && (
                  <Button size="sm" variant="outline" className="self-start" onClick={() => setEnding(s)} data-testid={`end-sign-in-${s.accountId}`}>
                    End sign-in
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </DetailSheet>
      {ending && person && (
        <ConfirmActionDialog
          open
          onOpenChange={(o) => !o && setEnding(null)}
          title={`End ${person.name}’s ${ending.appName} sign-in?`}
          consequence={`Agents stop acting as ${person.name} in ${ending.appName}. Their next call asks them to connect again, and the audit log records that you ended it.`}
          note={`${person.name} can connect again from My apps unless the app is turned off.`}
          runsNow
          destructive
          confirmLabel="End sign-in"
          isPending={end.isPending}
          onConfirm={async () => {
            await end.mutateAsync({ appId: ending.appId, accountId: ending.accountId, personId: person.personId });
            setEnding(null);
          }}
        />
      )}
    </>
  );
}

/**
 * Apps › People: one row per person who signed in to the team's apps, with their apps, counts that work, ended and
 * failed, and when any was last used, searched, filtered and paged on the server (GET /v1/apps/people). A row opens
 * the person's sign-ins, each with End sign-in. Only for people who may manage the team's apps; anyone else is told
 * which permission the page needs and no request is made.
 */
export function PeoplePage() {
  const may = useCan(MANAGE.area, MANAGE.action);
  const list = useListParams<PeopleFilters>('name', 20);
  const people = useAppPeople({ page: list.params.page, pageSize: list.params.pageSize, search: list.params.search, filters: list.params.filters, enabled: may === true });
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const data = people.data;
  const rows: Row[] = React.useMemo(
    () => (data?.data ?? []).map((p) => ({ ...p, onRowClick: () => setOpenId(p.personId), rowTestId: `person-row-${p.personId}` })),
    [data],
  );
  const index = rows.findIndex((r) => r.personId === openId);
  const open = index >= 0 ? rows[index] : null;
  const appLabels = data?.labels?.app ?? {};
  const appOptions = Object.entries(data?.facets.app ?? {}).map(([value, count]) => ({ value, label: appLabels[value] ?? value, count }));
  const stateOptions = (['connected', 'expired', 'refused'] as const).map((value) => ({ value, label: STATE_WORDS[value].label, count: data?.facets.state?.[value] ?? 0 }));
  return (
    <PageLayout icon={Plug} title="Apps" switcher description="Who signed in to the team’s apps, which sign-ins work, and which need attention." tabs={<AppsTabs />} contentClassName="flex flex-col gap-4">
      {may === false ? (
        <NoAccess what="who signed in to the team’s apps" needs={MANAGE} />
      ) : !data && (people.isError || people.failureCount > 0) ? (
        <QueryError what="people’s sign-ins" error={people.error ?? people.failureReason} onRetry={() => people.refetch()} retrying={people.isFetching} testId="people-error" />
      ) : may === undefined || people.isPending || !data ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : (
        <div data-testid="people-table">
          <DataTableWithViews
            columns={columns}
            data={rows}
            getRowId={(r) => r.personId}
            defaultView="table"
            hideViewSwitcher
            searchColumn="name"
            searchPlaceholder="Search people"
            filters={[
              { column: 'app', title: 'App', options: appOptions },
              { column: 'state', title: 'State', options: stateOptions },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            filterResetKey={filterResetKey}
            serverPagination={{
              enabled: true,
              total: data.pagination.total,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: data.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: people.isFetching && people.isPlaceholderData,
            }}
            emptyState={
              <ListEmpty
                icon={Users}
                noun="sign-ins"
                filtered={list.isFiltered}
                onClear={() => setFilterResetKey((k) => k + 1)}
                description="Nobody has signed in to the team’s apps yet. People connect from My apps, or the first time an agent needs their account."
              />
            }
          />
        </div>
      )}
      <PersonSheet
        person={open}
        onClose={() => setOpenId(null)}
        navigation={
          open
            ? {
                currentIndex: index,
                totalCount: rows.length,
                onPrev: index > 0 ? () => setOpenId(rows[index - 1].personId) : undefined,
                onNext: index < rows.length - 1 ? () => setOpenId(rows[index + 1].personId) : undefined,
              }
            : undefined
        }
      />
    </PageLayout>
  );
}
