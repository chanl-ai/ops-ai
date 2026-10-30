'use client';

import * as React from 'react';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { type MockAnswer, useAddMockAnswer, useChangeMockAnswer, useDeleteMockAnswer, useMockAnswers } from '@/hooks/systems-queries';

interface Draft {
  name: string;
  match: string;
  status: string;
  body: string;
  delayMs: string;
  timeout: boolean;
  default: boolean;
}

const draftOf = (m?: MockAnswer): Draft => ({
  name: m?.name ?? '',
  match: m && Object.keys(m.match ?? {}).length ? JSON.stringify(m.match, null, 2) : '',
  status: String(m?.status ?? 200),
  body: m?.body === undefined || m?.body === null ? '' : JSON.stringify(m.body, null, 2),
  delayMs: String(m?.delayMs ?? 0),
  timeout: m?.timeout ?? false,
  default: m?.default ?? false,
});

/** A JSON box's value, or why it is not JSON; an empty box is `empty`. */
function parsed(text: string, empty: unknown): { value?: unknown; error?: string } {
  if (!text.trim()) return { value: empty };
  try {
    return { value: JSON.parse(text) };
  } catch (e) {
    return { error: `Not valid JSON: ${(e as Error).message}` };
  }
}

/** What a mock answer does, in a few words: its status, or that it times out, and any wait. */
const outcome = (m: MockAnswer) => [m.timeout ? 'Times out' : `Answers ${m.status}`, m.delayMs ? `after ${m.delayMs} ms` : null].filter(Boolean).join(' ');
const when = (m: MockAnswer) => {
  const pairs = Object.entries(m.match ?? {});
  return pairs.length ? `When ${pairs.map(([k, v]) => `${k} is ${JSON.stringify(v)}`).join(' and ')}` : 'Any call';
};

/**
 * An operation's mock answers (c-580), in the order they are tried: the first whose match equals the call's inputs
 * answers, and the one marked default answers anything else. Each is saved at once, not staged with the operation.
 */
export function MockAnswers({ moduleId, opId }: { moduleId: string; opId: string }) {
  const mocks = useMockAnswers(moduleId, opId);
  const remove = useDeleteMockAnswer(moduleId, opId);
  const [editing, setEditing] = React.useState<{ mock?: MockAnswer } | null>(null);
  const list = mocks.data?.data ?? [];

  return (
    <Section
      title="Mock answers"
      description="Tried in order: the first whose match equals the call's inputs answers it, and the default answers the rest."
      flush
      actions={
        <Button type="button" size="sm" variant="outline" onClick={() => setEditing({})} data-testid="mock-add">
          <Plus />
          Add answer
        </Button>
      }
    >
      {mocks.isPending ? (
        <div className="flex flex-col gap-2 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : mocks.isError ? (
        <QueryError what="the mock answers" error={mocks.error} onRetry={() => void mocks.refetch()} retrying={mocks.isFetching} />
      ) : !list.length ? (
        <p className="p-4 text-sm text-muted-foreground" data-testid="mock-empty">
          No mock answers yet. Without one, a run against the mock answers with the operation's own example.
        </p>
      ) : (
        <Rows testId="mock-answers">
          {list.map((m) => (
            <Row
              key={m.id}
              wrap
              title={
                <span className="flex items-center gap-2">
                  {m.name}
                  {m.default && <Badge variant="secondary">Default</Badge>}
                </span>
              }
              description={`${when(m)} · ${outcome(m)}`}
              trailing={
                <>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setEditing({ mock: m })} data-testid={`mock-edit-${m.id}`}>
                    Edit
                  </Button>
                  <LoadingButton
                    type="button"
                    size="sm"
                    variant="ghost"
                    isLoading={remove.isPending && remove.variables === m.id}
                    onClick={() => remove.mutate(m.id, { onError: (e) => toast.error('Couldn’t delete the answer', { description: e.message }) })}
                    data-testid={`mock-delete-${m.id}`}
                  >
                    Delete
                  </LoadingButton>
                </>
              }
            />
          ))}
        </Rows>
      )}
      {editing && <MockAnswerDialog moduleId={moduleId} opId={opId} mock={editing.mock} onClose={() => setEditing(null)} />}
    </Section>
  );
}

function MockAnswerDialog({ moduleId, opId, mock, onClose }: { moduleId: string; opId: string; mock?: MockAnswer; onClose: () => void }) {
  const [d, setD] = React.useState<Draft>(() => draftOf(mock));
  const add = useAddMockAnswer(moduleId, opId);
  const change = useChangeMockAnswer(moduleId, opId);
  const match = parsed(d.match, {});
  const body = parsed(d.body, null);
  const status = Number(d.status);
  const delay = Number(d.delayMs || 0);
  const matchError =
    match.error ??
    (match.value !== null && typeof match.value === 'object' && !Array.isArray(match.value)
      ? undefined
      : 'Give an object of input names and the values to match.');
  const statusError = Number.isInteger(status) && status >= 100 && status <= 599 ? undefined : 'A status from 100 to 599.';
  const delayError = Number.isInteger(delay) && delay >= 0 && delay <= 30_000 ? undefined : 'From 0 to 30000 ms.';
  const ok = d.name.trim() && !matchError && !body.error && !statusError && !delayError;
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));

  const save = async () => {
    if (!ok) return;
    const values = {
      name: d.name.trim(),
      match: match.value as Record<string, unknown>,
      status,
      body: body.value,
      delayMs: delay,
      timeout: d.timeout,
      default: d.default,
    };
    try {
      if (mock) await change.mutateAsync({ mockId: mock.id, body: values });
      else await add.mutateAsync({ ...values, environment: 'test', headers: {} });
      toast.success(`Saved ${values.name}`);
      onClose();
    } catch (e) {
      toast.error('Couldn’t save the answer', { description: (e as Error).message });
    }
  };

  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="md"
      title={mock ? `Edit ${mock.name}` : 'Add a mock answer'}
      description="What a run against the mock gets back when its inputs match."
      data-testid="mock-dialog"
      onSubmit={() => void save()}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={add.isPending || change.isPending} disabled={!ok} data-testid="mock-save">
            Save
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="mock-name" label="Name">
          <Input id="mock-name" value={d.name} onChange={(e) => set({ name: e.target.value })} placeholder="Account not found" />
        </FormField>
        <FormField
          id="mock-match"
          label="Match"
          optional
          hint="Input names and the values they must equal. Empty matches every call."
          error={d.match.trim() ? matchError : undefined}
        >
          <Textarea
            id="mock-match"
            rows={3}
            value={d.match}
            onChange={(e) => set({ match: e.target.value })}
            className="font-mono text-xs"
            placeholder={'{"accountId": "acc-404"}'}
          />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="mock-status" label="Status" error={statusError}>
            <Input id="mock-status" type="number" min={100} max={599} value={d.status} onChange={(e) => set({ status: e.target.value })} disabled={d.timeout} />
          </FormField>
          <FormField id="mock-delay" label="Wait before answering (ms)" optional error={delayError}>
            <Input id="mock-delay" type="number" min={0} max={30000} value={d.delayMs} onChange={(e) => set({ delayMs: e.target.value })} />
          </FormField>
        </div>
        <FormField id="mock-body" label="Body" optional error={body.error}>
          <Textarea
            id="mock-body"
            rows={6}
            value={d.body}
            onChange={(e) => set({ body: e.target.value })}
            className="font-mono text-xs"
            placeholder={'{"error": "not_found"}'}
            disabled={d.timeout}
          />
        </FormField>
        <label className="flex items-center justify-between gap-3 text-sm" htmlFor="mock-timeout">
          <span>
            <span className="block font-medium">Times out</span>
            <span className="block text-xs text-muted-foreground">The call waits and gets no answer, as when the system is down.</span>
          </span>
          <Switch id="mock-timeout" checked={d.timeout} onCheckedChange={(v) => set({ timeout: v })} />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm" htmlFor="mock-default">
          <span>
            <span className="block font-medium">Default</span>
            <span className="block text-xs text-muted-foreground">Answers every call no other answer matches. Only one is the default.</span>
          </span>
          <Switch id="mock-default" checked={d.default} onCheckedChange={(v) => set({ default: v })} />
        </label>
      </div>
    </DialogShell>
  );
}
