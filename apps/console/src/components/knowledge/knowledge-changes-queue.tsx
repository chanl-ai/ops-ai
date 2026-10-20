'use client';

import * as React from 'react';
import { AlertTriangle, BookOpenCheck, CheckCircle2, Inbox, UserCheck } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { ConflictChip, FreshnessChip, ORIGIN_OPTIONS, OriginChip, TrustChip } from '@/components/knowledge/changes/change-chips';
import { type ChangeRow, changeColumns } from '@/components/knowledge/changes/change-columns';
import { ChangeDetailBody } from '@/components/knowledge/changes/change-detail';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { useKnowledgeChange, useKnowledgeChanges } from '@/hooks/knowledge-change-queries';
import { useKnowledgeBases } from '@/hooks/knowledge-queries';
import { useListParams } from '@/hooks/use-list-params';
import type { ChangeFilters, ChangeView, KnowledgeChange } from '@/lib/types/knowledge-changes';

/**
 * Proposed knowledge edits. Rendered across all knowledge bases under Reviews, and for one
 * knowledge base on its Changes tab (`kbId`). The open change lives in `?change=` so notifications link to it.
 */
export function KnowledgeChangesQueue({ kbId }: { kbId?: string }) {
  const [view, setView] = React.useState<ChangeView>('open');
  const list = useListParams<ChangeFilters>('summary');
  const query = useKnowledgeChanges({ ...list.params, view, kbId });
  const kbs = useKnowledgeBases({ page: 1, pageSize: 100 });

  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const activeId = searchParams.get('change');
  const setActiveId = React.useCallback(
    (id: string | null) => {
      const next = new URLSearchParams(searchParams.toString());
      if (id) next.set('change', id);
      else next.delete('change');
      const q = next.toString();
      router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const rows = query.data?.data ?? [];
  const activeIndex = rows.findIndex((r) => r.id === activeId);
  const offPage = useKnowledgeChange(activeId && activeIndex < 0 ? activeId : null);
  const active = activeIndex >= 0 ? rows[activeIndex] : (offPage.data ?? null);
  const tableRows: ChangeRow[] = React.useMemo(() => rows.map((r) => ({ ...r, onRowClick: (x: KnowledgeChange) => setActiveId(x.id), rowTestId: `change-row-${r.id}` })), [rows, setActiveId]);

  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { label: string; value: string }[]) => options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={6} />;
  if (query.isError && !query.data) return <QueryError what="knowledge changes" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />;

  return (
    <div className="flex flex-col gap-4">
      <SavedViewTabs
        ariaLabel="Change views"
        presets={[
          { id: 'mine', label: `Changes · ${counts?.mine ?? 0}`, icon: UserCheck },
          { id: 'open', label: `All open · ${counts?.open ?? 0}`, icon: Inbox },
          { id: 'conflicts', label: `Conflicts · ${counts?.conflicts ?? 0}`, icon: AlertTriangle },
          { id: 'resolved', label: `Decided · ${counts?.resolved ?? 0}`, icon: CheckCircle2 },
        ]}
        savedViews={[]}
        activePresetId={view}
        activeSavedViewId={null}
        onSelectPreset={(id) => {
          setView(id as ChangeView);
          list.reset();
        }}
        onSelectSavedView={() => undefined}
        onSaveView={() => undefined}
        onDeleteView={() => undefined}
        canSave={false}
      />

      <DataTableWithViews
        columns={changeColumns}
        data={tableRows}
        getRowId={(r) => r.id}
        searchColumn="summary"
        searchPlaceholder="Search changes…"
        hideViewSwitcher
        initialColumnVisibility={kbId ? { kbId: false, citedBy: false } : { citedBy: false }}
        filters={[
          { column: 'origin', title: 'From', options: withCounts('origin', ORIGIN_OPTIONS) },
          ...(kbId ? [] : [{ column: 'kbId', title: 'Knowledge base', options: withCounts('kbId', (kbs.data?.data ?? []).map((k) => ({ label: k.name, value: k.id }))) }]),
          { column: 'owner', title: 'Owner', options: withCounts('owner', Object.keys(facets.owner ?? {}).map((o) => ({ label: o, value: o }))) },
        ]}
        onColumnFiltersChange={list.onColumnFiltersChange}
        serverPagination={{
          enabled: true,
          total: query.data?.pagination.total ?? 0,
          page: list.pagination.page,
          pageSize: list.pagination.pageSize,
          totalPages: query.data?.pagination.totalPages,
          onPaginationChange: list.setPagination,
          isLoading: query.isFetching && query.isPlaceholderData,
        }}
        emptyState={
          <ListEmpty
            icon={BookOpenCheck}
            noun={view === 'resolved' ? 'decided changes' : 'changes'}
            filtered={list.isFiltered}
            description={
              view === 'mine'
                ? 'Changes to documents you own appear here.'
                : 'Edits from curation, agents’ suggested fixes and source syncs that change a cited passage appear here before agents see them.'
            }
          />
        }
      />

      <DetailSheet
        open={!!active}
        onOpenChange={(o) => !o && setActiveId(null)}
        title={active?.summary}
        description={active ? `${active.id} · ${active.documentTitle} · owner ${active.owner}` : undefined}
        tags={
          active && (
            <>
              <OriginChip origin={active.origin} />
              <TrustChip state={active.trust} />
              <FreshnessChip change={active} />
              {active.conflict && <ConflictChip resolved={!!active.conflict.resolution} />}
            </>
          )
        }
        navigation={
          active && activeIndex >= 0
            ? {
                currentIndex: activeIndex + (list.pagination.page - 1) * list.pagination.pageSize,
                totalCount: Math.max(query.data?.pagination.total ?? rows.length, 1),
                onPrev: activeIndex > 0 ? () => setActiveId(rows[activeIndex - 1].id) : undefined,
                onNext: activeIndex < rows.length - 1 ? () => setActiveId(rows[activeIndex + 1].id) : undefined,
              }
            : undefined
        }
        widthClass="sm:max-w-2xl"
        testId="change-sheet"
        scrollKey={active?.id}
      >
        {active && <ChangeDetailBody change={active} />}
      </DetailSheet>
    </div>
  );
}
