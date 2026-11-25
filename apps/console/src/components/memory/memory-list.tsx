'use client';

import * as React from 'react';
import { Brain, Download, Pencil, SearchX, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { labelOf } from '@/components/shared/readable-value';
import { SearchSelect } from '@/components/shared/search-select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { useCorrectMemory, useExportMemories, useForgetAgentMemories, useForgetMemory, useMemories } from '@/hooks/memory-queries';
import { agentOptions } from '@/hooks/options-queries';
import { useDebounced } from '@/hooks/use-debounced';
import { plural } from '@/lib/format';
import type { Memory } from '@/lib/types/memory';

const KIND: Record<Memory['kind'], string> = { fact: 'Fact', preference: 'Preference', episode: 'Earlier chat' };
const PAGE = 20;

/**
 * What agents remember about the signed-in person, which they correct, forget and export. With `agentId` it shows
 * what one agent uses (the chat's What I remember sheet); without, every agent's, newest first, with an agent filter
 * (My account > Memory). The search, the agent and the page are the server's: a person with thousands of memories
 * loads one page.
 */
export function MemoryList({ agentId }: { agentId?: string }) {
  const [search, setSearch] = React.useState('');
  const [picked, setPicked] = React.useState<{ id: string; label: string } | null>(null);
  const [page, setPage] = React.useState(1);
  const words = useDebounced(search.trim());
  const agent = agentId ?? picked?.id;
  const q = useMemories({ page, pageSize: PAGE, search: words || undefined, agentId: agent });
  const rows = q.data?.data ?? [];
  const paging = q.data?.pagination;
  const narrowed = !!words || (!agentId && !!picked);

  if (q.isPending && !q.data)
    return (
      <div className="space-y-2" data-testid="memory-list-loading">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  if (q.isError && !q.data) return <QueryError what="what agents remember" onRetry={() => q.refetch()} retrying={q.isFetching} error={q.error} />;

  return (
    <div className="space-y-4" data-testid="memory-list">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          {agentId ? 'What this agent keeps about you between chats.' : 'What each agent keeps about you between chats.'} Only you see it.
        </p>
        <ExportButton />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input value={search} onChange={(e) => (setSearch(e.target.value), setPage(1))} placeholder="Search memories…" aria-label="Search memories" className="min-w-0 flex-1 sm:max-w-xs" data-testid="memory-search" />
        {!agentId && (
          <SearchSelect source={agentOptions} value={picked} onChange={(id, o) => (setPicked(id ? { id, label: o?.label ?? id } : null), setPage(1))} placeholder="All agents" noneLabel="All agents" searchPlaceholder="Search agents…" emptyText="No agent matches." testId="memory-agent" />
        )}
        {agent && <ForgetAll agentId={agent} agentName={picked?.label ?? rows.find((m) => m.agentId === agent)?.agentName ?? 'This agent'} />}
      </div>
      {rows.length === 0 ? (
        narrowed ? (
          <EmptyState icon={SearchX} title="No memory matches" description="Try other words, or another agent." testId="memory-none-match" />
        ) : (
          <EmptyState
            icon={Brain}
            title="Nothing remembered yet"
            description="When you tell an agent something about yourself, like your timezone or how you like answers, it shows here."
            testId="memory-empty"
          />
        )
      ) : (
        <ItemGroup className="gap-2" aria-busy={q.isFetching && q.isPlaceholderData}>
          {rows.map((m) => (
            <MemoryRow key={m.id} memory={m} showAgent={!agent} />
          ))}
        </ItemGroup>
      )}
      {paging && paging.totalPages > 1 && (
        <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground" data-testid="memory-pages">
          <span>
            Page {paging.page} of {paging.totalPages} · {plural(paging.total, 'memory', 'memories')}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!paging.hasPrev} onClick={() => setPage(paging.page - 1)} data-testid="memory-prev">
              Previous
            </Button>
            <Button variant="outline" size="sm" disabled={!paging.hasNext} onClick={() => setPage(paging.page + 1)} data-testid="memory-next">
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Forgets everything one agent keeps about the person; the toast says how many the server forgot. */
function ForgetAll({ agentId, agentName }: { agentId: string; agentName: string }) {
  const [confirm, setConfirm] = React.useState(false);
  const forgetAll = useForgetAgentMemories();
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setConfirm(true)} data-testid="memory-forget-all">
        Forget all
      </Button>
      <DeleteDialog
        open={confirm}
        onOpenChange={setConfirm}
        verb="Forget"
        entityType="memories"
        description={`${agentName} forgets everything it keeps about you, at once. Your next chat with it starts without it.`}
        isLoading={forgetAll.isPending}
        testIdPrefix="memory-all"
        onConfirm={async () => {
          const { forgotten } = await forgetAll.mutateAsync(agentId);
          setConfirm(false);
          toast.success(`${agentName} forgot ${forgotten} ${forgotten === 1 ? 'memory' : 'memories'}`);
        }}
      />
    </>
  );
}

function MemoryRow({ memory: m, showAgent }: { memory: Memory; showAgent: boolean }) {
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(m.value);
  const [confirm, setConfirm] = React.useState(false);
  const correct = useCorrectMemory();
  const forget = useForgetMemory();
  const label = m.key ? labelOf(m.key) : KIND[m.kind];

  const save = async () => {
    try {
      await correct.mutateAsync({ id: m.id, value: value.trim() });
      setEditing(false);
    } catch (e) {
      toast.error('Couldn’t save the correction', { description: (e as Error).message });
    }
  };

  return (
    <Item role="listitem" variant="outline" size="sm" data-testid="memory-row" data-key={m.key ?? ''}>
      <ItemContent>
        <ItemTitle>
          <span>{label}</span>
          <Badge variant="secondary">{KIND[m.kind]}</Badge>
          {showAgent && <Badge variant="outline">{m.agentId ? m.agentName : 'Every agent'}</Badge>}
          {m.source === 'person' && <Badge variant="outline">Corrected by you</Badge>}
        </ItemTitle>
        {editing ? (
          <form
            className="flex flex-wrap gap-2 pt-1"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <Input value={value} onChange={(e) => setValue(e.target.value)} maxLength={2000} className="min-w-0 flex-1" aria-label={`New value for ${label}`} data-testid="memory-value-input" autoFocus />
            <LoadingButton type="submit" size="sm" isLoading={correct.isPending} disabled={!value.trim() || value.trim() === m.value} data-testid="memory-save">
              Save
            </LoadingButton>
            <Button type="button" variant="ghost" size="sm" onClick={() => (setEditing(false), setValue(m.value))}>
              Cancel
            </Button>
          </form>
        ) : (
          <ItemDescription data-testid="memory-value">{m.value}</ItemDescription>
        )}
      </ItemContent>
      {!editing && (
        <ItemActions>
          <Button variant="ghost" size="icon" className="size-8" onClick={() => setEditing(true)} aria-label={`Correct ${label}`} data-testid="memory-edit">
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" onClick={() => setConfirm(true)} aria-label={`Forget ${label}`} data-testid="memory-forget">
            <Trash2 className="size-4" />
          </Button>
        </ItemActions>
      )}
      <DeleteDialog
        open={confirm}
        onOpenChange={setConfirm}
        verb="Forget"
        entityType="memory"
        entityName={label}
        description="It is removed at once, with its earlier versions, and the agent no longer uses it."
        isLoading={forget.isPending}
        testIdPrefix="memory"
        onConfirm={async () => {
          await forget.mutateAsync(m.id);
          setConfirm(false);
        }}
      />
    </Item>
  );
}

function ExportButton() {
  const exp = useExportMemories();
  const go = async () => {
    try {
      const data = await exp.mutateAsync();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = 'my-memories.json';
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Downloaded my-memories.json', { description: `${data.memories.length} memories and their history.` });
    } catch (e) {
      toast.error('Couldn’t export your memories', { description: (e as Error).message });
    }
  };
  return (
    <LoadingButton variant="outline" size="sm" isLoading={exp.isPending} onClick={go} data-testid="memory-export">
      <Download className="size-4" /> Export
    </LoadingButton>
  );
}
