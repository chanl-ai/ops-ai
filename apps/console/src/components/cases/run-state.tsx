'use client';

import Link from 'next/link';
import { AlertCircle, ScrollText } from 'lucide-react';

import { WidgetView } from '@/components/chat/widget-view';
import { FieldSectionLabel } from '@/components/shared/field-row';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { ChildThread, RunThreadState, StateObject, ToolFailure } from '@/lib/types/cases';
import type { Cell, WidgetPart } from '@/lib/types/widgets';

// The engine's bookkeeping and the trigger's input: not what the workflow found, so not drawn as parts.
const ENGINE_KEYS = new Set(['email', 'attachments', 'extractions', 'visited', 'grade_overrides', 'decision', 'pending', 'agent_decision', 'review_id', 'draft', 'score', 'feedback', 'text', 'children', 'tool_error', 'status', 'record_count']);

const isObject = (v: unknown): v is StateObject => typeof v === 'object' && v !== null && !Array.isArray(v);
const cell = (v: unknown): Cell => (v === null || v === undefined ? null : typeof v === 'object' ? JSON.stringify(v) : typeof v === 'boolean' || typeof v === 'number' ? v : String(v));
/** One object as a widget row: nested objects contribute `outer.inner` keys, anything deeper is written out. */
const flat = (o: StateObject): Record<string, Cell> => Object.fromEntries(Object.entries(o).flatMap(([k, v]) => (isObject(v) ? Object.entries(v).map(([ik, iv]) => [`${k}.${ik}`, cell(iv)]) : [[k, cell(v)]])));
const title = (key: string) => key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

/** The workflow's own state fields as widget parts: a list of objects is rows, one object is a record. */
function parts(values: RunThreadState['values']): WidgetPart[] {
  const out: WidgetPart[] = [];
  for (const [key, v] of Object.entries(values)) {
    if (ENGINE_KEYS.has(key)) continue;
    if (Array.isArray(v) && v.length && v.every(isObject)) out.push({ type: 'widget', id: key, shape: 'rows', data: v.map(flat), hint: { title: `${title(key)} · ${v.length}` } });
    else if (isObject(v) && Object.keys(v).length) out.push({ type: 'widget', id: key, shape: 'record', data: flat(v), hint: { title: title(key) } });
  }
  return out;
}

function ToolError({ error }: { error: ToolFailure }) {
  return (
    <Alert variant="destructive" data-testid="run-tool-error">
      <AlertCircle />
      <AlertDescription>
        {error.action} was refused{error.status ? ` (${error.status})` : ''}: {error.message} The run waits for a new decision; nothing retried the call.
      </AlertDescription>
    </Alert>
  );
}

/**
 * What a run holds beyond its row and trace, drawn the way chat draws tool results: every field the workflow wrote
 * to its state as a widget part by its shape (c-055 registry), the runs it opened (`children` on the row, each with
 * its current outcome) as links into Cases, a refused call as an alert. Nothing here names a workflow; a run whose
 * state holds only the engine's fields shows nothing.
 */
export function RunStateDetail({ runId, state, children, isPending, isError, onRetry }: { runId: string; state?: RunThreadState; children?: ChildThread[] | null; isPending: boolean; isError: boolean; onRetry: () => void }) {
  if (isPending)
    return (
      <div className="flex flex-col gap-2" data-testid="run-state-loading">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  if (isError || !state) return <QueryError what="the run’s state" onRetry={onRetry} testId="run-state-error" />;
  const v = state.values;
  const error = v.tool_error ?? state.interrupt?.payload.error ?? null;
  const opened = (children ?? []).filter((c) => c.threadId);
  const drawn = parts(v);
  if (!drawn.length && !opened.length && !error) return null;
  return (
    <div className="flex flex-col gap-5" data-testid="run-state">
      {error && <ToolError error={error} />}
      {v.status && (
        <p className="text-sm" data-testid="run-state-status">
          Ended <span className="font-medium">{title(v.status)}</span>
        </p>
      )}
      {drawn.map((part) => (
        <div key={part.id} data-testid={`run-part-${part.id}`}>
          <WidgetView part={part} />
        </div>
      ))}
      {opened.length > 0 && (
        <section className="flex flex-col gap-2" data-testid="run-children">
          <FieldSectionLabel>Cases opened · {opened.length}</FieldSectionLabel>
          <div className="overflow-hidden rounded-lg border bg-card">
            <Rows>
              {opened.map((c) => (
                <Row
                  key={c.threadId!}
                  href={`/workflows/runs?run=${encodeURIComponent(c.threadId!)}`}
                  title={[c.name, c.customerId ? `(${c.customerId})` : ''].filter(Boolean).join(' ') || c.subject || c.threadId!}
                  description={c.caseNo ? `Case ${c.caseNo}` : undefined}
                  trailing={
                    <>
                      <span className="text-xs" data-testid="child-outcome">{c.outcome ? title(c.outcome) : c.status ? title(c.status) : '—'}</span>
                      <span className="font-mono text-xs text-muted-foreground">{c.threadId}</span>
                    </>
                  }
                />
              ))}
            </Rows>
          </div>
          <Button asChild size="sm" variant="ghost" className="self-start">
            <Link href={`/workflows/runs?parent=${encodeURIComponent(runId)}`} data-testid="run-children-list">List them in Runs</Link>
          </Button>
        </section>
      )}
      <Button asChild size="sm" variant="outline" className="self-start">
        <Link href={`/logs/tool-calls?run=${encodeURIComponent(runId)}`} data-testid="run-activity-link">
          <ScrollText className="size-3.5" /> Tool calls behind this run
        </Link>
      </Button>
    </div>
  );
}
