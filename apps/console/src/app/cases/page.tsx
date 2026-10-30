'use client';

import * as React from 'react';
import { Clock, Inbox, Layers, Mail, UserRound } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';

import { caseRecordColumns, PRIORITY_OPTIONS, STATUS_OPTIONS } from '@/components/cases/case-record-columns';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { useCaseRecords } from '@/hooks/case-record-queries';
import { useMe } from '@/hooks/me-queries';
import { useListParams } from '@/hooks/use-list-params';
import type { CaseRecordFilters, CaseStatus } from '@/lib/types/case-records';

type View = 'open' | 'mine' | 'overdue' | 'all';
const OPEN: CaseStatus[] = ['open', 'waiting_on_us', 'waiting_on_customer'];
const EMPTY: Record<View, { noun: string; description: string }> = {
  open: { noun: 'open cases', description: 'Cases appear here when a person, an agent or a workflow opens one for a customer.' },
  mine: { noun: 'cases assigned to you', description: 'Cases you own appear here.' },
  overdue: { noun: 'overdue cases', description: 'Every open case is inside its resolution deadline.' },
  all: { noun: 'cases', description: 'Cases appear here when a person, an agent or a workflow opens one for a customer.' },
};

/**
 * Cases: the team's customer issues (agents-service /v1/cases, c-220), each with who it is for, who owns it and the
 * time left to its two deadlines. The server filters and orders them, soonest resolution deadline first. Workflow runs
 * are under Workflows › Runs; an old `/cases?run=` link is sent there.
 */
export default function CasesPage() {
  const router = useRouter();
  const search = useSearchParams();
  const me = useMe().data?.user.email;
  const [view, setView] = React.useState<View>('open');
  const list = useListParams<{ status?: string[]; priority?: string[] }>('subject');

  const legacy = search.get('run') ?? search.get('parent');
  React.useEffect(() => {
    if (legacy) router.replace(`/workflows/runs?${search.toString()}`);
  }, [legacy, router, search]);

  const chosen = list.params.filters?.status as CaseStatus[] | undefined;
  const filters: CaseRecordFilters = {
    search: list.params.search || undefined,
    status: chosen?.length ? chosen : view === 'all' ? undefined : view === 'overdue' ? undefined : OPEN,
    priority: (list.params.filters?.priority as CaseRecordFilters['priority']) || undefined,
    assignee: view === 'mine' ? me : undefined,
    overdue: view === 'overdue' || undefined,
  };
  const query = useCaseRecords({ page: list.pagination.page, pageSize: list.pagination.pageSize, ...filters });
  const rows = query.data?.data ?? [];

  if (legacy) return <PageLayout icon={Mail} title="Cases"><PageSkeleton statCards={0} tableRows={4} /></PageLayout>;
  return (
    <PageLayout icon={Mail} title="Cases" description="Your team's customer issues: who each is for, who owns it, and the time left to its first response and resolution.">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="cases" error={query.error} onRetry={() => query.refetch()} retrying={query.isFetching} testId="cases-error" />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="Case views"
            presets={[
              { id: 'open', label: 'Open', icon: Inbox },
              { id: 'mine', label: 'Mine', icon: UserRound },
              { id: 'overdue', label: 'Overdue', icon: Clock },
              { id: 'all', label: 'All', icon: Layers },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as View);
              list.reset();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <DataTableWithViews
            key={view}
            columns={caseRecordColumns}
            // Both deadlines are what this list is for, so they stay shown past the table's default of five columns.
            initialColumnVisibility={{ response: true, resolution: true }}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="subject"
            searchPlaceholder="Search subject or customer…"
            filters={[
              { column: 'status', title: 'Status', options: STATUS_OPTIONS },
              { column: 'priority', title: 'Priority', options: PRIORITY_OPTIONS },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            hideViewSwitcher
            serverPagination={{
              enabled: true,
              total: query.data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: query.data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={Mail} noun={EMPTY[view].noun} filtered={!!(list.params.search || chosen?.length || filters.priority?.length)} onClear={list.reset} description={EMPTY[view].description} />}
          />
        </div>
      )}
    </PageLayout>
  );
}
