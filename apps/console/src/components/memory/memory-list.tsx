'use client';

import * as React from 'react';
import { Brain, Download, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { useCorrectMemory, useExportMemories, useForgetAgentMemories, useForgetMemory, useMemories } from '@/hooks/memory-queries';
import type { Memory } from '@/lib/types/memory';

const KIND: Record<Memory['kind'], string> = { fact: 'Fact', preference: 'Preference', episode: 'Earlier chat' };

/**
 * What agents remember about the signed-in person, which they correct, forget and export (c-206). With `agentId` it
 * shows one agent's (the chat's What I remember sheet); without, every agent's grouped by agent (My account > Memory).
 */
export function MemoryList({ agentId }: { agentId?: string }) {
  const q = useMemories(agentId);
  const groups = React.useMemo(() => {
    const by = new Map<string, Memory[]>();
    for (const m of q.data ?? []) by.set(m.agentId, [...(by.get(m.agentId) ?? []), m]);
    return [...by.values()];
  }, [q.data]);

  if (q.isPending)
    return (
      <div className="space-y-2" data-testid="memory-list-loading">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  if (q.isError) return <QueryError what="what agents remember" onRetry={() => q.refetch()} retrying={q.isFetching} error={q.error} />;

  return (
    <div className="space-y-4" data-testid="memory-list">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          {agentId ? 'What this agent keeps about you between chats.' : 'What each agent keeps about you between chats.'} Only you see it.
        </p>
        <ExportButton />
      </div>
      {groups.length === 0 ? (
        <EmptyState
          icon={Brain}
          title="Nothing remembered yet"
          description="When you tell an agent something about yourself, like your timezone or how you like answers, it shows here."
          testId="memory-empty"
        />
      ) : (
        groups.map((rows) => <AgentGroup key={rows[0].agentId} rows={rows} showName={!agentId} />)
      )}
    </div>
  );
}

function AgentGroup({ rows, showName }: { rows: Memory[]; showName: boolean }) {
  const [confirm, setConfirm] = React.useState(false);
  const forgetAll = useForgetAgentMemories();
  const { agentId, agentName } = rows[0];
  return (
    <section className="space-y-2" data-testid="memory-group" data-agent={agentId}>
      <div className="flex items-center justify-between gap-2">
        {showName ? <h3 className="text-sm font-medium">{agentName}</h3> : <span />}
        <Button variant="ghost" size="sm" onClick={() => setConfirm(true)} data-testid="memory-forget-all">
          Forget all
        </Button>
      </div>
      <ItemGroup className="gap-2">
        {rows.map((m) => (
          <MemoryRow key={m.id} memory={m} />
        ))}
      </ItemGroup>
      <DeleteDialog
        open={confirm}
        onOpenChange={setConfirm}
        verb="Forget"
        entityType="memories"
        count={rows.length}
        description={`${agentName} forgets everything it keeps about you, at once. Your next chat with it starts without it.`}
        isLoading={forgetAll.isPending}
        testIdPrefix="memory-all"
        onConfirm={async () => {
          const { forgotten } = await forgetAll.mutateAsync(agentId);
          setConfirm(false);
          toast.success(`${agentName} forgot ${forgotten} ${forgotten === 1 ? 'memory' : 'memories'}`);
        }}
      />
    </section>
  );
}

function MemoryRow({ memory: m }: { memory: Memory }) {
  const [editing, setEditing] = React.useState(false);
  const [value, setValue] = React.useState(m.value);
  const [confirm, setConfirm] = React.useState(false);
  const correct = useCorrectMemory();
  const forget = useForgetMemory();
  const label = m.key ?? KIND[m.kind];

  const save = async () => {
    try {
      await correct.mutateAsync({ id: m.id, value: value.trim() });
      setEditing(false);
    } catch (e) {
      toast.error('Couldn’t save the correction', { description: (e as Error).message });
    }
  };

  return (
    <Item variant="outline" size="sm" data-testid="memory-row" data-key={m.key ?? ''}>
      <ItemContent>
        <ItemTitle>
          <span className="capitalize">{label}</span>
          <Badge variant="secondary">{KIND[m.kind]}</Badge>
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
