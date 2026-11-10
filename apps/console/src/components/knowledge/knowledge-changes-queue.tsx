'use client';

import * as React from 'react';
import { BookOpenCheck, CheckCircle2, Inbox, ListChecks, UserCheck, XCircle } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { ORIGIN_OPTIONS, OriginChip, TrustChip } from '@/components/knowledge/changes/change-chips';
import { type ChangeRow, changeColumns, decidable } from '@/components/knowledge/changes/change-columns';
import { ChangeDetailBody } from '@/components/knowledge/changes/change-detail';
import { FaqDraftEditor, needsSave } from '@/components/knowledge/changes/faq-draft-editor';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { countLabel, SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { serverPagination } from '@/components/shared/server-pagination';
import { useDecideChanges, useEditChange, useKnowledgeChange, useKnowledgeChanges } from '@/hooks/knowledge-change-queries';
import { useListParams } from '@/hooks/use-list-params';
import { plural } from '@/lib/format';
import type { ChangeFilters, ChangeView, KnowledgeChange } from '@/lib/types/knowledge-changes';

/**
 * Knowledge changes: the FAQ drafts waiting for review beside the versions syncs applied. Rendered across all knowledge
 * bases under Reviews, and for one base on its Changes tab (`kbId`). A draft is approved, rejected or edited here, one
 * at a time from its sheet or many at once from the selection. The open change lives in `?change=`.
 */
export function KnowledgeChangesQueue({ kbId }: { kbId?: string }) {
  const [view, setView] = React.useState<ChangeView>('open');
  const list = useListParams<ChangeFilters>('summary');
  const query = useKnowledgeChanges({ ...list.params, view, kbId });
  const decide = useDecideChanges();
  const edit = useEditChange();
  const [busy, setBusy] = React.useState<'save' | 'approve' | 'reject' | null>(null);
  const [clearSelection, setClearSelection] = React.useState(0);

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

  const run = React.useCallback(
    async (ids: string[], decision: 'approve' | 'reject') => {
      try {
        await decide.mutateAsync({ ids, decision });
        toast.success(`${decision === 'approve' ? 'Approved' : 'Rejected'} ${plural(ids.length, 'FAQ draft')}`, { description: decision === 'approve' ? 'Approved pairs are searchable now and cite their passage.' : undefined });
        setClearSelection((n) => n + 1);
        return true;
      } catch (e) {
        toast.error(`Couldn’t ${decision} ${plural(ids.length, 'draft')}`, { description: (e as Error).message });
        return false;
      }
    },
    [decide],
  );

  const rows = query.data?.data ?? [];
  const activeIndex = rows.findIndex((r) => r.id === activeId);
  const offPage = useKnowledgeChange(activeId && activeIndex < 0 ? activeId : null);
  const active = activeIndex >= 0 ? rows[activeIndex] : (offPage.data ?? null);
  const tableRows: ChangeRow[] = React.useMemo(() => rows.map((r) => ({ ...r, onRowClick: (x: KnowledgeChange) => setActiveId(x.id), rowTestId: `change-row-${r.id}` })), [rows, setActiveId]);
  const columns = React.useMemo(() => changeColumns({ onEdit: (c) => setActiveId(c.id), onReject: (c) => void run([c.id], 'reject') }), [setActiveId, run]);

  const act = async (what: 'save' | 'approve' | 'reject', pair: { question: string; answer: string }) => {
    if (!active) return;
    setBusy(what);
    try {
      if (what !== 'reject' && needsSave(active, pair)) await edit.mutateAsync({ id: active.id, ...pair });
      if (what === 'save') toast.success('Draft saved', { description: 'It still waits for review.' });
      else if (await run([active.id], what)) setActiveId(null);
    } catch (e) {
      toast.error('Couldn’t save the draft', { description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

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
          { id: 'open', label: countLabel('Open', counts?.open), icon: Inbox },
          { id: 'mine', label: countLabel('Mine', counts?.mine), icon: UserCheck },
          { id: 'resolved', label: countLabel('Decided', counts?.resolved), icon: CheckCircle2 },
          { id: 'all', label: 'All', icon: ListChecks },
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
        columns={columns}
        data={tableRows}
        getRowId={(r) => r.id}
        searchColumn="summary"
        searchPlaceholder="Search questions and documents…"
        hideViewSwitcher
        rowNoun="change"
        filters={[{ column: 'origin', title: 'From', options: withCounts('origin', ORIGIN_OPTIONS) }]}
        bulkActions={[
          { label: 'Reject', icon: XCircle, variant: 'outline', onClick: (picked) => void run(picked.filter(decidable).map((r) => r.id), 'reject') },
          { label: 'Approve', icon: CheckCircle2, onClick: (picked) => void run(picked.filter(decidable).map((r) => r.id), 'approve') },
        ]}
        selectionResetKey={clearSelection}
        onColumnFiltersChange={list.onColumnFiltersChange}
        serverPagination={serverPagination(list, query)}
        emptyState={
          <ListEmpty
            icon={BookOpenCheck}
            noun={view === 'resolved' ? 'decided changes' : view === 'open' || view === 'mine' ? 'FAQ drafts waiting' : 'changes'}
            filtered={list.isFiltered}
            description={
              view === 'mine'
                ? 'FAQ drafts of sources whose knowledge you own appear here.'
                : 'Drafts appear here after a sync of a source with FAQ drafts on. Approved pairs become searchable; each cites its passage.'
            }
          />
        }
      />

      <DetailSheet
        open={!!active}
        onOpenChange={(o) => !o && setActiveId(null)}
        title={active?.faq ? 'FAQ draft' : active?.summary}
        description={active ? `${active.documentTitle} · ${active.sourceName} · ${active.toVersion}` : undefined}
        tags={
          active && (
            <>
              <OriginChip origin={active.origin} />
              <TrustChip state={active.trust} />
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
        {active && (active.faq ? <FaqDraftEditor change={active} busy={busy} onAct={act} /> : <ChangeDetailBody change={active} />)}
      </DetailSheet>
    </div>
  );
}
