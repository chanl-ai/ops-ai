'use client';

import { PromptDiff } from '@/components/prompts/prompt-diff';
import { PlainValue, labelOf } from '@/components/shared/readable-value';
import { Row, Rows } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import type { DefinitionDiff, FieldChange } from '@/lib/types/engine';

const FIELD_WORDS: Record<string, string> = { name: 'Name', type: 'Kind of step', typeVersion: 'Step version', onError: 'When it fails', description: 'Description' };

/** A setting's name as a person reads it: `parameters.maxToolCalls` reads "Max tool calls". */
export const fieldWords = (field: string) => FIELD_WORDS[field] ?? labelOf(field.replace(/^parameters\./, ''));

/** The count line a version row shows: "3 steps changed, 1 added". */
export function changeCount(d: DefinitionDiff): string {
  const parts = [
    d.changed.length && `${d.changed.length} ${d.changed.length === 1 ? 'step' : 'steps'} changed`,
    d.added.length && `${d.added.length} added`,
    d.removed.length && `${d.removed.length} removed`,
    d.moved.length && `${d.moved.length} moved`,
    (d.connected.length || d.disconnected.length) && 'connections changed',
    d.workflow.length && 'settings changed',
  ].filter(Boolean);
  return parts.join(', ') || 'No change';
}

/** One setting, old to new: text as a line diff (an agent step's prompt), anything else as old and new values. */
function FieldDiff({ change }: { change: FieldChange }) {
  const { before, after } = change;
  const text = (typeof before === 'string' || before == null) && (typeof after === 'string' || after == null);
  return (
    <div className="flex min-w-0 flex-col gap-1" data-testid="definition-field-change" data-field={change.field}>
      <span className="text-xs font-medium text-muted-foreground">{fieldWords(change.field)}</span>
      {text ? (
        <PromptDiff before={String(before ?? '')} after={String(after ?? '')} />
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <div className="min-w-0 rounded-md bg-muted/50 p-2 break-all">
            <span className="block text-xs text-muted-foreground">Before</span>
            {before === undefined || before === null ? <span className="text-muted-foreground">Not set</span> : <PlainValue value={before} />}
          </div>
          <div className="min-w-0 rounded-md bg-muted/50 p-2 break-all">
            <span className="block text-xs text-muted-foreground">After</span>
            {after === undefined || after === null ? <span className="text-muted-foreground">Not set</span> : <PlainValue value={after} />}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * What changed between two states of a workflow, from the server's diff: each changed step with every setting that
 * differs, then the steps added, removed and moved. `detail` shows each setting old and new (the compare sheet);
 * without it a step lists its settings by name (the publish dialog).
 */
export function ChangesList({ diff, detail = false }: { diff: DefinitionDiff; detail?: boolean }) {
  const none = !diff.changed.length && !diff.added.length && !diff.removed.length && !diff.moved.length && !diff.workflow.length && !diff.connected.length && !diff.disconnected.length;
  if (none) return <p className="text-sm text-muted-foreground">No change.</p>;
  return (
    <Rows testId="definition-changes">
      {diff.workflow.length > 0 && (
        <Row wrap={detail} title="Workflow settings" description={detail ? undefined : diff.workflow.map((f) => fieldWords(f.field)).join(', ')}>
          {detail && diff.workflow.map((f) => <FieldDiff key={f.field} change={f} />)}
        </Row>
      )}
      {diff.changed.map((s) => (
        <Row key={s.id} wrap={detail} title={s.name} trailing={<Badge variant="outline">Changed</Badge>} description={detail ? undefined : s.fields.map((f) => fieldWords(f.field)).join(', ')}>
          {detail && <div className="mt-2 flex w-full flex-col gap-3">{s.fields.map((f) => <FieldDiff key={f.field} change={f} />)}</div>}
        </Row>
      ))}
      {diff.added.map((s) => (
        <Row key={s.id} title={s.name} trailing={<Badge variant="outline">Added</Badge>} />
      ))}
      {diff.removed.map((s) => (
        <Row key={s.id} title={s.name} trailing={<Badge variant="outline">Removed</Badge>} />
      ))}
      {diff.moved.map((s) => (
        <Row key={s.id} title={s.name} trailing={<Badge variant="outline">Moved</Badge>} />
      ))}
      {(diff.connected.length > 0 || diff.disconnected.length > 0) && <Row title="Connections" description={`${diff.connected.length} made, ${diff.disconnected.length} removed`} />}
    </Rows>
  );
}
