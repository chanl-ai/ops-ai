'use client';

import * as React from 'react';
import { AlertCircle, CheckCircle2, Clock, Inbox, Mail, ShieldCheck, UserPlus, Users, XCircle } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { caseColumns, type CaseTableRow } from '@/components/cases/case-columns';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { CASE_STATUS_LABEL } from '@/components/status-badges';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAssignCases, useCaseQueues, useCases, useCloseCases } from '@/hooks/case-queries';
import { useLookups } from '@/hooks/queries';
import { useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import type { CaseFilters, CaseRow, CaseView } from '@/lib/types/cases';

const PRIORITY_OPTIONS = (['urgent', 'high', 'normal', 'low'] as const).map((p) => ({ label: p[0].toUpperCase() + p.slice(1), value: p }));
const STATUS_OPTIONS = Object.entries(CASE_STATUS_LABEL)
  .filter(([v]) => v !== 'closed')
  .map(([value, label]) => ({ label, value }));
const CLOSE_REASONS = ['Resolved', 'Duplicate of another case', 'Not a request for us', 'Spam or phishing'];

export default function CasesPage() {
  const router = useRouter();
  const [view, setView] = React.useState<CaseView>('team');
  const list = useListParams<CaseFilters>('subject');
  const query = useCases({ ...list.params, view });
  const { data: queues } = useCaseQueues();
  const { data: lookups } = useLookups();
  const assign = useAssignCases();
  const close = useCloseCases();
  const [bulk, setBulk] = React.useState<{ kind: 'assign' | 'close'; rows: CaseRow[] } | null>(null);
  const shown = useSticky(bulk);
  const [selectionResetKey, setSelectionResetKey] = React.useState(0);
  const me = lookups?.currentUser.name;

  const rows = query.data?.data;
  const tableRows: CaseTableRow[] = React.useMemo(
    () => (rows ?? []).map((c) => ({ ...c, onRowClick: (x: CaseRow) => router.push(`/cases/${x.id}`), href: `/cases/${c.id}`, rowTestId: `case-row-${c.id}` })),
    [rows, router],
  );

  const counts = query.data?.viewCounts;
  const stats = query.data?.stats;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { label: string; value: string }[]) => options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  // Intent ids repeat across mailboxes (address_change), so the facet lists each id once with its first name.
  const intentOptions = React.useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of rows ?? []) if (!seen.has(c.intentId)) seen.set(c.intentId, c.intentName);
    for (const id of Object.keys(facets.intentId ?? {})) if (!seen.has(id)) seen.set(id, id.replace(/_/g, ' '));
    return [...seen].map(([value, label]) => ({ value, label }));
  }, [rows, facets.intentId]);

  const resetSelection = () => setSelectionResetKey((k) => k + 1);

  return (
    <PageLayout icon={Mail} title="Cases" description="Customer emails turned into cases, with the actions the agent drafted">
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="cases" onRetry={() => query.refetch()} retrying={query.isFetching} testId="cases-error" />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Open cases" value={stats?.open} icon={Inbox} footer={{ text: `${counts?.mine ?? 0} assigned to you`, subtext: 'Across all mailboxes' }} />
            <StatCard label="Past SLA" value={stats?.breaching} icon={AlertCircle} footer={{ text: stats?.breaching ? 'Oldest first in Past SLA' : 'Nothing overdue', subtext: 'SLA set per intent in routing' }} />
            <StatCard label="Waiting on approval" value={stats?.awaitingApproval} icon={ShieldCheck} footer={{ text: `${counts?.awaiting_me ?? 0} you can approve`, subtext: 'Drafted actions run only after sign-off' }} />
            <StatCard label="Closed today" value={stats?.closedToday} icon={CheckCircle2} footer={{ text: `${counts?.closed ?? 0} closed in total`, subtext: 'Since midnight' }} />
          </StatCardGrid>

          {query.isError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex items-center justify-between gap-2">
                Refreshing cases failed. These are the last results that loaded.
                <Button size="sm" variant="outline" onClick={() => query.refetch()}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <SavedViewTabs
            ariaLabel="Case views"
            presets={[
              { id: 'mine', label: `Assigned to me · ${counts?.mine ?? 0}` },
              { id: 'team', label: `All open · ${counts?.team ?? 0}`, icon: Inbox },
              { id: 'awaiting_me', label: `Awaiting my approval · ${counts?.awaiting_me ?? 0}`, icon: ShieldCheck },
              { id: 'breaching', label: `Past SLA · ${counts?.breaching ?? 0}`, icon: Clock },
              { id: 'closed', label: `Closed · ${counts?.closed ?? 0}` },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as CaseView);
              list.reset();
              resetSelection();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />

          <DataTableWithViews
            columns={caseColumns}
            data={tableRows}
            getRowId={(r) => r.id}
            searchColumn="subject"
            searchPlaceholder="Search subject, customer or case id…"
            initialColumnVisibility={{ confidence: false, mailbox: false }}
            filters={[
              { column: 'queue', title: 'Queue', options: withCounts('queue', (queues?.queues ?? []).map((q) => ({ label: q, value: q }))) },
              { column: 'intentId', title: 'Intent', options: withCounts('intentId', intentOptions) },
              { column: 'priority', title: 'Priority', options: withCounts('priority', PRIORITY_OPTIONS) },
              ...(view === 'closed' ? [] : [{ column: 'status', title: 'Status', options: withCounts('status', STATUS_OPTIONS) }]),
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={selectionResetKey}
            serverPagination={{
              enabled: true,
              total: query.data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: query.data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            bulkActions={
              view === 'closed'
                ? []
                : [
                    {
                      label: 'Assign to me',
                      icon: UserPlus,
                      variant: 'outline',
                      onClick: (selected) =>
                        me &&
                        assign.mutate(
                          { ids: selected.map((r) => r.id), assignee: me },
                          {
                            onSuccess: (res) => {
                              toastBulk(res, 'Assigned', 'case');
                              resetSelection();
                            },
                            onError: (e) => toast.error('Couldn’t assign those cases', { description: e.message }),
                          },
                        ),
                    },
                    { label: 'Assign', icon: Users, variant: 'outline', onClick: (rows) => setBulk({ kind: 'assign', rows }) },
                    { label: 'Close', icon: XCircle, variant: 'outline', onClick: (rows) => setBulk({ kind: 'close', rows }) },
                  ]
            }
            emptyState={
              <ListEmpty
                icon={Mail}
                noun={view === 'closed' ? 'closed cases' : 'cases'}
                filtered={list.isFiltered}
                createLabel={view === 'mine' || view === 'awaiting_me' ? 'Show all open cases' : 'Connect a mailbox'}
                onCreate={() => {
                  if (view === 'mine' || view === 'awaiting_me') {
                    setView('team');
                    list.reset();
                    resetSelection();
                  } else router.push('/deployments?create=1');
                }}
                description={
                  view === 'mine'
                    ? 'Nothing is assigned to you. Pick cases up from All open.'
                    : view === 'awaiting_me'
                      ? 'No drafted actions are waiting for your approval.'
                      : 'Each email to a connected mailbox opens a case here.'
                }
              />
            }
          />
        </div>
      )}

      <BulkFieldDialog
        open={bulk?.kind === 'assign'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Assign ${shown?.rows.length ?? 0} cases`}
        description="The assignee sees them in Assigned to me. SLA clocks keep running."
        fieldLabel="Assignee"
        options={queues?.assignees ?? []}
        names={(shown?.rows ?? []).map((r) => `${r.id} · ${r.subject}`)}
        confirmLabel="Assign"
        isPending={assign.isPending}
        onConfirm={async (assignee) => {
          const res = await assign.mutateAsync({ ids: bulk!.rows.map((r) => r.id), assignee });
          toastBulk(res, `Assigned to ${assignee}:`, 'case');
          resetSelection();
        }}
      />
      <BulkFieldDialog
        open={bulk?.kind === 'close'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Close ${shown?.rows.length ?? 0} cases`}
        description="Cases with actions still waiting for approval stay open. Decide or reject those actions first."
        fieldLabel="Reason"
        options={CLOSE_REASONS}
        names={(shown?.rows ?? []).map((r) => `${r.id} · ${r.subject}`)}
        confirmLabel="Close cases"
        isPending={close.isPending}
        onConfirm={async (reason) => {
          const res = await close.mutateAsync({ ids: bulk!.rows.map((r) => r.id), reason });
          toastBulk(res, 'Closed', 'case');
          resetSelection();
        }}
      />
    </PageLayout>
  );
}
