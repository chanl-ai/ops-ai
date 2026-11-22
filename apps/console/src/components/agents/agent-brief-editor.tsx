'use client';

import * as React from 'react';

import { InstructionDocument, referencesIn, type DocumentValue, type InstructionDocumentHandle } from '@/components/shared/instruction-document';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useReferenceLabels, useReferenceSearch } from '@/hooks/references-queries';
import type { AgentBrief, PromptMode } from '@/lib/types/domain';
import type { PublishBlocker, Ref } from '@/lib/types/references';

export const EMPTY_BRIEF: AgentBrief = { purpose: '', goal: '', howToAnswer: '', never: [], success: [] };

/** The brief an agent without one starts from: its job line is the Purpose and its instructions are How to answer. */
export const legacyBrief = (a: { role: string; instructions: string }): AgentBrief => ({ ...EMPTY_BRIEF, purpose: a.role, howToAnswer: a.instructions });

const toValue = (b: AgentBrief, only: 'all' | 'never'): DocumentValue => ({
  blocks: [
    ...(only === 'all'
      ? ([
          { kind: 'field', key: 'brief.purpose', label: 'Purpose', locked: true, text: b.purpose, placeholder: 'What this agent is for, in a sentence. Type @ to name a tool, knowledge or skill.' },
          { kind: 'field', key: 'brief.goal', label: 'Goal', locked: true, text: b.goal, placeholder: 'What a good outcome looks like for the person it helps.' },
          { kind: 'field', key: 'brief.howToAnswer', label: 'How to answer', locked: true, text: b.howToAnswer, placeholder: 'Tone, order and what to include. Type @ to start a skill.' },
        ] as const)
      : []),
    { kind: 'list', key: 'brief.never', label: 'Never', items: b.never, placeholder: 'Something this agent must never do. It is kept in every prompt.' },
    ...(only === 'all' ? ([{ kind: 'list', key: 'brief.success', label: 'Success checks', items: b.success, placeholder: 'How a reviewer can tell a good answer. Shown to people who review its work.' }] as const) : []),
  ],
});

const text = (v: DocumentValue, key: string) => v.blocks.flatMap((b) => (b.kind === 'field' && b.key === key ? [b.text] : [])).join('\n');
const list = (v: DocumentValue, key: string) => v.blocks.flatMap((b) => (b.kind === 'list' && b.key === key ? b.items : []));

/**
 * An agent's prompt as a brief: Purpose, Goal, How to answer, Never and Success checks as one document. In plain-text
 * mode the builder's own text is the prompt and only Never is kept from the brief, so it is the one heading shown
 * beside the text. The document is a view of the saved brief; `@` lists what the agent's team offers.
 */
export function AgentBriefEditor({
  agentId,
  name,
  brief,
  onBrief,
  mode,
  instructions,
  onInstructions,
  readOnly,
  problems,
  onInsert,
  controls,
  toolbar,
  footer,
  textareaRef,
}: {
  agentId: string;
  name: string;
  brief: AgentBrief;
  onBrief: (next: AgentBrief) => void;
  mode: PromptMode;
  instructions: string;
  onInstructions: (next: string) => void;
  readOnly?: boolean;
  /** The publish check's problems: one that names a heading is written under it. */
  problems?: PublishBlocker[];
  /** Grants the agent what a pick or "Add it back" names. */
  onInsert: (ref: Ref) => Promise<void> | void;
  controls?: React.Ref<InstructionDocumentHandle>;
  /** Plain-text mode only: the prompt builder and "Attach always-on skill", and the note under the text. */
  toolbar?: React.ReactNode;
  footer?: React.ReactNode;
  textareaRef?: React.Ref<HTMLTextAreaElement>;
}) {
  const context = React.useMemo(() => ({ forAgent: agentId }), [agentId]);
  const only = mode === 'full' ? 'never' : 'all';
  const document = React.useMemo(() => toValue(brief, only), [brief, only]);
  const ids = React.useMemo(() => referencesIn(document).map((r) => `${r.kind}:${r.id}`), [document]);
  const labels = useReferenceLabels(context, ids);
  const search = useReferenceSearch(context);
  const invalid = React.useMemo(
    () => (problems ?? []).filter((p) => p.kind !== 'missing_reference' && p.position?.field.startsWith('brief.')).map((p) => ({ field: p.position!.field, message: p.message })),
    [problems],
  );
  const onChange = (next: DocumentValue) =>
    onBrief(
      only === 'all'
        ? { purpose: text(next, 'brief.purpose'), goal: text(next, 'brief.goal'), howToAnswer: text(next, 'brief.howToAnswer'), never: list(next, 'brief.never'), success: list(next, 'brief.success') }
        : { ...brief, never: list(next, 'brief.never') },
    );
  return (
    <div className="flex flex-col gap-3" data-testid="agent-brief">
      {mode === 'full' && (
        <div className="flex flex-col gap-2">
          {toolbar && <div className="flex flex-wrap justify-end gap-2">{toolbar}</div>}
          <Textarea ref={textareaRef} value={instructions} onChange={(e) => onInstructions(e.target.value)} disabled={readOnly} rows={12} className="bg-card font-mono text-xs leading-relaxed" aria-label="Instructions" data-testid="agent-plain-text" />
          <p className="text-xs text-muted-foreground">Brief fields other than Never are not used while this is on. Never is written after your text.</p>
          {footer}
        </div>
      )}
      <InstructionDocument
        label={`${name} brief`}
        value={document}
        onChange={onChange}
        searchReferences={search}
        onInsertReference={onInsert}
        resolved={labels.data}
        missing={problems}
        invalid={invalid}
        controls={controls}
        readOnly={readOnly}
        hint="Type @ to add a tool, knowledge, skill or agent"
      />
    </div>
  );
}

/** The two links under the document: switching how the prompt is written. */
export function PromptModeToggle({ mode, onChoose, disabled }: { mode: PromptMode; onChoose: (to: PromptMode) => void; disabled?: boolean }) {
  return (
    <Button type="button" variant="link" size="sm" className="self-start" disabled={disabled} onClick={() => onChoose(mode === 'brief' ? 'full' : 'brief')} data-testid="agent-prompt-mode">
      {mode === 'brief' ? 'Edit as plain text' : 'Back to the brief'}
    </Button>
  );
}
