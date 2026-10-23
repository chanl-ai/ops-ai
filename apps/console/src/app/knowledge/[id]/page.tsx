'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ChevronDown, Play, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { KbDot, KbHealthBadge } from '@/components/knowledge/knowledge-meta';
import { KbOverview } from '@/components/knowledge/kb-overview';
import { retireBase } from '@/components/knowledge/retire-base';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { BuilderFieldset } from '@/components/shared/builder-only';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useDeleteKb, useKnowledgeBase, useRefreshKb, useRetryKbFailed } from '@/hooks/knowledge-queries';
import { useKnowledgeChanges } from '@/hooks/knowledge-change-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useTabParam } from '@/hooks/use-tab-param';
import { count, relativeTime } from '@/lib/format';

import { KbDocumentsTab } from '../_parts/kb-documents-tab';
import { KbPlaygroundTab } from '../_parts/kb-playground-tab';
import { KbSourcesTab } from '../_parts/kb-sources-tab';
import { KnowledgeChangesQueue } from '@/components/knowledge/knowledge-changes-queue';

// No Retrieval tab: kb-service answers with the base's keyword search and reads no saved retrieval settings yet.
const TABS = ['overview', 'sources', 'documents', 'changes', 'playground'] as const;
type Tab = (typeof TABS)[number];
// Documents are added and managed under Sources (c-159). The documents view stays a route so a citation or a failure
// count can open a document, but it is not offered as a tab.
const SHOWN = TABS.filter((t) => t !== 'documents');
const LABEL: Record<Tab, string> = { overview: 'Overview', sources: 'Sources', documents: 'Documents', changes: 'Changes', playground: 'Playground' };

export default function KnowledgeBasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'overview');
  const changes = useKnowledgeChanges({ page: 1, pageSize: 1, view: 'open', kbId: id });
  const query = useKnowledgeBase(id);
  const refresh = useRefreshKb();
  const retry = useRetryKbFailed();
  const remove = useDeleteKb();
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const teamCanBuild = useCanBuild();

  if (query.isPending)
    return (
      <PageLayout title="Knowledge base" backHref="/knowledge">
        <PageSkeleton statCards={5} tableRows={4} showToolbar={false} />
      </PageLayout>
    );
  if (query.isError)
    return (
      <PageLayout title="Knowledge base" backHref="/knowledge">
        <QueryError what="this knowledge base" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} back={{ label: 'Back to knowledge bases', href: '/knowledge' }} />
      </PageLayout>
    );

  const kb = query.data;
  // The knowledge base's own flags (its detail asks the write routes' check); the team's permission until they load.
  const canBuild = kb.canEdit ?? teamCanBuild;
  const canDelete = kb.canDelete ?? teamCanBuild;
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
          <Button className={canBuild ? 'rounded-r-none' : undefined} onClick={() => setTab('playground')}>
            <Play className="size-4" /> Open playground
          </Button>
          {canBuild && (
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
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive" disabled={!canDelete} onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          )}
        </div>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as Tab)}>
          <TabsList>
            {SHOWN.map((t) => (
              <TabsTrigger key={t} value={t}>
                {LABEL[t]}
                {t === 'sources' && <span className="ml-1 text-muted-foreground tabular-nums">{kb.sources.length}</span>}
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
      {/* Searching (documents, playground) is reading; refreshing, retrying and changing sources are a builder's. */}
      <BuilderFieldset canEdit={kb.canEdit}>
      {tab === 'overview' && (
        <KbOverview
          kb={kb}
          busy={refresh.isPending || retry.isPending}
          onRefresh={doRefresh}
          onRetryFailed={() => retry.mutate(kb.id, { onSuccess: () => toast.success('Retrying failed documents'), onError: fail('retry') })}
          tabHref={tabHref}
        />
      )}
      {tab === 'sources' && <KbSourcesTab kb={kb} />}
      </BuilderFieldset>
      {tab === 'documents' && <KbDocumentsTab kb={kb} />}
      {tab === 'playground' && <KbPlaygroundTab kb={kb} />}
      {tab === 'changes' && <KnowledgeChangesQueue kbId={kb.id} />}

      <DeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        entityType="knowledge base"
        entityName={kb.name}
        requireNameConfirmation={retireBase(kb).requireName}
        description={retireBase(kb).description}
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
