'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ChevronDown, Copy, Play, RefreshCw, SearchX, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { KbDot, KbHealthBadge } from '@/components/knowledge/knowledge-meta';
import { KbOverview } from '@/components/knowledge/kb-overview';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useCancelKbJob, useDeleteKb, useDuplicateKb, useKnowledgeBase, useRefreshKb, useRetryKbFailed } from '@/hooks/knowledge-queries';
import { useKnowledgeChanges } from '@/hooks/knowledge-change-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { ApiError } from '@/lib/api';
import { count, relativeTime } from '@/lib/format';

import { KbDocumentsTab } from '../_parts/kb-documents-tab';
import { KbPlaygroundTab } from '../_parts/kb-playground-tab';
import { KbRetrievalTab } from '../_parts/kb-retrieval-tab';
import { KbSourcesTab } from '../_parts/kb-sources-tab';
import { KnowledgeChangesQueue } from '@/components/knowledge/knowledge-changes-queue';

const TABS = ['overview', 'sources', 'documents', 'changes', 'retrieval', 'playground'] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { overview: 'Overview', sources: 'Sources', documents: 'Documents', changes: 'Changes', retrieval: 'Retrieval', playground: 'Playground' };

export default function KnowledgeBasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'overview');
  const changes = useKnowledgeChanges({ page: 1, pageSize: 1, view: 'open', kbId: id });
  const query = useKnowledgeBase(id);
  const refresh = useRefreshKb();
  const retry = useRetryKbFailed();
  const cancel = useCancelKbJob();
  const duplicate = useDuplicateKb();
  const remove = useDeleteKb();
  const [deleteOpen, setDeleteOpen] = React.useState(false);

  if (query.isPending)
    return (
      <PageLayout title="Knowledge base" backHref="/knowledge">
        <PageSkeleton statCards={5} tableRows={4} showToolbar={false} />
      </PageLayout>
    );
  if (query.isError)
    return (
      <PageLayout title="Knowledge base" backHref="/knowledge">
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState icon={SearchX} title="Knowledge base not found" description="It may have been deleted, or the link is wrong." action={{ label: 'Back to knowledge bases', href: '/knowledge' }} />
        ) : (
          <QueryError what="this knowledge base" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        )}
      </PageLayout>
    );

  const kb = query.data;
  const fail = (what: string) => (e: Error) => toast.error(`Couldn’t ${what}`, { description: e.message });
  const doRefresh = () => refresh.mutate(kb.id, { onSuccess: () => toast.success(kb.health === 'never' ? 'Index build started' : 'Index refresh started'), onError: fail('refresh the index') });
  const tabHref = (t: string, q?: string) => `/knowledge/${kb.id}?tab=${t}${q ? `&${q}` : ''}`;

  return (
    <PageLayout
      icon={<KbDot color={kb.color} className="size-3.5" />}
      title={kb.name}
      badge={<KbHealthBadge health={kb.health} />}
      description={
        <span>
          {kb.description} <span className="text-xs">· {kb.collections.length ? `Collections: ${kb.collections.join(', ')}` : 'All collections'} · refreshed {relativeTime(kb.lastRefreshedAt)}</span>
        </span>
      }
      backHref="/knowledge"
      actions={
        <div className="flex items-center">
          <Button className="rounded-r-none" onClick={() => setTab('playground')}>
            <Play className="size-4" /> Open playground
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button className="rounded-l-none border-l border-primary-foreground/20 px-2" aria-label="More actions">
                <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={!!kb.indexing} onClick={doRefresh}>
                <RefreshCw className="size-4" /> Refresh index
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  duplicate.mutate(kb.id, {
                    onSuccess: (c) => {
                      toast.success(`Duplicated as ${c.name}`, { description: 'Settings and source links are copied; build its index to use it.' });
                      router.push(`/knowledge/${c.id}`);
                    },
                    onError: fail('duplicate'),
                  })
                }
              >
                <Copy className="size-4" /> Duplicate
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t}>
                {LABEL[t]}
                {t === 'sources' && <span className="ml-1 text-muted-foreground tabular-nums">{kb.sources.length}</span>}
                {t === 'documents' && <span className="ml-1 text-muted-foreground tabular-nums">{count(kb.stats.documents)}</span>}
                {t === 'changes' && !!changes.data?.viewCounts.open && (
                  <span className="ml-1 rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground tabular-nums" aria-label={`${changes.data.viewCounts.open} open`}>
                    {changes.data.viewCounts.open}
                  </span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
    >
      {tab === 'overview' && (
        <KbOverview
          kb={kb}
          busy={refresh.isPending || retry.isPending || cancel.isPending}
          onRefresh={doRefresh}
          onRetryFailed={() => retry.mutate(kb.id, { onSuccess: () => toast.success('Retrying failed documents'), onError: fail('retry') })}
          onCancel={() => cancel.mutate(kb.id, { onSuccess: () => toast.message('Refresh cancelled', { description: 'Documents already processed stay indexed.' }), onError: fail('cancel') })}
          tabHref={tabHref}
        />
      )}
      {tab === 'sources' && <KbSourcesTab kb={kb} />}
      {tab === 'documents' && <KbDocumentsTab kb={kb} />}
      {tab === 'retrieval' && <KbRetrievalTab kb={kb} onTestInPlayground={() => setTab('playground')} />}
      {tab === 'playground' && <KbPlaygroundTab kb={kb} />}
      {tab === 'changes' && <KnowledgeChangesQueue kbId={kb.id} />}

      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="knowledge base"
        entityName={kb.name}
        requireNameConfirmation={kb.agentNames.length > 0}
        description={
          kb.agentNames.length
            ? `${kb.agentNames.join(', ')} cite this knowledge base and lose access to it. Sources and their items are kept.`
            : 'The index and its retrieval settings are removed. Sources and their items are kept.'
        }
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(kb.id);
            toast.success(`Deleted ${kb.name}`);
            router.push('/knowledge');
          } catch (e) {
            toast.error(`Couldn’t delete ${kb.name}`, { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
