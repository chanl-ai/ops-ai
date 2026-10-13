'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { FlaskConical, Gavel, History, Scale, ShieldAlert, ShieldCheck, ShieldX, TestTubes } from 'lucide-react';
import { toast } from 'sonner';

import { evidenceColumns, gateColumns, judgeColumns, runColumns, suiteColumns, type Clickable } from '@/components/assurance/assurance-columns';
import { KIND_OPTIONS, TIER_OPTIONS, TRIGGER_LABEL } from '@/components/assurance/assurance-meta';
import { JudgeSheet } from '@/components/assurance/judge-sheet';
import { SuiteSheet } from '@/components/assurance/suite-sheet';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { openLink } from '@/components/files/file-actions';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAssurance, useExportBundle } from '@/hooks/assurance-queries';
import { useDownloadFile } from '@/hooks/file-queries';
import { useListParams } from '@/hooks/use-list-params';
import { useTabParam } from '@/hooks/use-tab-param';
import { pct, plural } from '@/lib/format';
import type { AssuranceFilters, AssuranceJudge, AssuranceRow, AssuranceSuite, AssuranceTab, EvidenceBundleRow } from '@/lib/types/assurance';

const TABS = ['suites', 'runs', 'gates', 'evidence', 'judges'] as const satisfies readonly AssuranceTab[];
const TAB_LABEL: Record<AssuranceTab, string> = { suites: 'Suites', runs: 'Runs', gates: 'Gates', evidence: 'Evidence', judges: 'Judges' };
const RESULT_OPTIONS: Record<'suites' | 'gates', { value: string; label: string }[]> = {
  suites: [
    { value: 'failing', label: 'Failing' },
    { value: 'passing', label: 'Passing' },
    { value: 'not_run', label: 'Not run' },
  ],
  gates: [
    { value: 'blocked', label: 'Blocked' },
    { value: 'ready', label: 'Waiting on a reviewer' },
    { value: 'decided', label: 'Decided' },
  ],
};
const EMPTY: Record<AssuranceTab, { icon: typeof Scale; noun: string; description: string }> = {
  suites: { icon: TestTubes, noun: 'suites', description: 'Every agent, skill and workflow gets a suite when it is created. Add cases from its page.' },
  runs: { icon: FlaskConical, noun: 'eval runs', description: 'Runs appear when a version is saved, a publish is requested, a model updates or knowledge changes.' },
  gates: { icon: ShieldCheck, noun: 'publish gates', description: 'A gate is evaluated for each publish request. Request a publish from a workflow to see one here.' },
  evidence: { icon: History, noun: 'evidence bundles', description: 'A bundle is sealed each time a publish request is approved.' },
  judges: { icon: Gavel, noun: 'judges', description: 'Judges score rubric checks. The platform team adds and calibrates them.' },
};

export default function AssurancePage() {
  const [tab, setTab] = useTabParam(TABS, 'suites');
  const list = useListParams<AssuranceFilters>('name');
  const query = useAssurance({ ...list.params, tab });
  const exportBundle = useExportBundle();
  const download = useDownloadFile();
  const [exportingId, setExportingId] = React.useState<string | null>(null);
  const [openId, setOpenId] = React.useState<string | null>(null);

  const data = query.data;
  const rows = (data?.data ?? []) as AssuranceRow[];
  const facets = data?.facets ?? {};
  const withCounts = (column: string, options: { value: string; label: string }[]) => options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const stats = data?.stats;
  const counts = data?.tabCounts;

  const changeTab = (t: AssuranceTab) => {
    setOpenId(null);
    list.reset();
    setTab(t);
  };

  const onExport = async (b: EvidenceBundleRow) => {
    setExportingId(b.id);
    try {
      const f = await exportBundle.mutateAsync(b.id);
      toast.success(`Exported ${b.asset.name} v${b.version} evidence`, {
        description: `${f.name} is in Files. The sealed bundle is unchanged.`,
        action: {
          label: 'Download',
          onClick: async () => {
            try {
              openLink(await download.mutateAsync(f.id), f.name);
            } catch (e) {
              toast.error('Couldn’t download', { description: (e as Error).message });
            }
          },
        },
      });
    } catch (e) {
      toast.error('Couldn’t export the bundle', { description: (e as Error).message });
    } finally {
      setExportingId(null);
    }
  };

  // Suites and judges open a sheet; the sheet steps through the rows on this page.
  const sheetRows = rows as (AssuranceSuite | AssuranceJudge)[];
  const openIndex = sheetRows.findIndex((r) => r.id === openId);
  const navigation = openIndex >= 0 ? { currentIndex: openIndex, totalCount: sheetRows.length, onPrev: openIndex > 0 ? () => setOpenId(sheetRows[openIndex - 1].id) : undefined, onNext: openIndex < sheetRows.length - 1 ? () => setOpenId(sheetRows[openIndex + 1].id) : undefined } : undefined;
  const clickable = <T extends { id: string }>(r: T): Clickable<T> => ({ ...r, onRowClick: (x: T) => setOpenId(x.id), rowTestId: `${tab}-row-${r.id}` });

  const table = (() => {
    switch (tab) {
      case 'suites':
        return {
          columns: suiteColumns as ColumnDef<AssuranceRow>[],
          data: (rows as AssuranceSuite[]).map(clickable),
          filters: [
            { column: 'kind', title: 'Kind', options: withCounts('kind', KIND_OPTIONS) },
            { column: 'tier', title: 'Risk tier', options: withCounts('tier', TIER_OPTIONS) },
            { column: 'result', title: 'Result', options: withCounts('result', RESULT_OPTIONS.suites) },
          ],
          hidden: { kind: false, result: false, lastRunAt: false },
          search: 'Search assets…',
        };
      case 'runs':
        return {
          columns: runColumns as ColumnDef<AssuranceRow>[],
          data: rows,
          filters: [
            { column: 'kind', title: 'Kind', options: withCounts('kind', KIND_OPTIONS) },
            { column: 'trigger', title: 'Trigger', options: withCounts('trigger', Object.entries(TRIGGER_LABEL).map(([value, label]) => ({ value, label }))) },
          ],
          hidden: { kind: false },
          search: 'Search runs…',
        };
      case 'gates':
        return {
          columns: gateColumns as ColumnDef<AssuranceRow>[],
          data: rows,
          filters: [
            { column: 'tier', title: 'Risk tier', options: withCounts('tier', TIER_OPTIONS) },
            { column: 'result', title: 'Status', options: withCounts('result', RESULT_OPTIONS.gates) },
          ],
          hidden: {},
          search: 'Search publish requests…',
        };
      case 'evidence':
        return { columns: evidenceColumns(onExport, exportingId) as ColumnDef<AssuranceRow>[], data: rows, filters: [{ column: 'kind', title: 'Kind', options: withCounts('kind', KIND_OPTIONS) }], hidden: { kind: false }, search: 'Search bundles…' };
      case 'judges':
        return { columns: judgeColumns as ColumnDef<AssuranceRow>[], data: (rows as AssuranceJudge[]).map(clickable), filters: [], hidden: {}, search: 'Search judges…' };
    }
  })();
  const empty = EMPTY[tab];

  return (
    <PageLayout
      switcher
      icon={ShieldCheck}
      title="Evals"
      description="Suites, runs, gates and evidence for every agent, skill and workflow"
      tabs={
        <div className="flex flex-col gap-2">
          <Tabs value={tab} onValueChange={(t) => changeTab(t as AssuranceTab)}>
            <TabsList>
              {TABS.map((t) => (
                <TabsTrigger key={t} value={t} data-testid={`assurance-tab-${t}`}>
                  {TAB_LABEL[t]}
                  {counts && <span className="ml-1 text-muted-foreground tabular-nums">{counts[t]}</span>}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={8} />
      ) : query.isError && !data ? (
        <QueryError what="assurance" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Failing suites" value={stats?.failingSuites} icon={ShieldX} footer={{ text: 'Latest run has a failing case', subtext: 'Agents, skills and workflows' }} />
            <StatCard label="Gates blocked" value={stats?.gatesBlocked} icon={ShieldAlert} footer={{ text: 'Open publish requests', subtext: 'A blocking step failed' }} />
            <StatCard label="Live without evidence" value={stats?.liveUnsealed} icon={History} footer={{ text: 'Live versions with no sealed bundle', subtext: 'Published before sealing' }} />
            <StatCard
              label="Lowest judge agreement"
              value={stats?.lowestJudge ? pct(stats.lowestJudge.agreement) : '—'}
              icon={Gavel}
              footer={{ text: stats?.lowestJudge?.name ?? 'No judges yet', subtext: 'Agreement with reviewer labels' }}
            />
          </StatCardGrid>

          <DataTableWithViews
            key={tab}
            columns={table.columns}
            data={table.data}
            getRowId={(r) => ('id' in r ? r.id : r.reviewId)}
            searchColumn="name"
            searchPlaceholder={table.search}
            initialColumnVisibility={table.hidden as Record<string, boolean>}
            filters={table.filters}
            onColumnFiltersChange={list.onColumnFiltersChange}
            serverPagination={{
              enabled: true,
              total: data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={empty.icon} noun={empty.noun} filtered={list.isFiltered} description={empty.description} />}
          />
          {tab === 'suites' && counts && counts.suites > 0 && <p className="text-xs text-muted-foreground">{plural(stats?.failingSuites ?? 0, 'suite')} failing. Draft cases from rejected reviews wait for their owner before the gate runs them.</p>}
        </div>
      )}

      <SuiteSheet suite={tab === 'suites' && openIndex >= 0 ? (sheetRows[openIndex] as AssuranceSuite) : null} open={tab === 'suites' && openIndex >= 0} onOpenChange={(o) => !o && setOpenId(null)} navigation={navigation} />
      <JudgeSheet judge={tab === 'judges' && openIndex >= 0 ? (sheetRows[openIndex] as AssuranceJudge) : null} open={tab === 'judges' && openIndex >= 0} onOpenChange={(o) => !o && setOpenId(null)} navigation={navigation} />
    </PageLayout>
  );
}
