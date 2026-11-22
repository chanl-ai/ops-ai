'use client';

import * as React from 'react';

import { InstructionDocument, referencesIn, type DocumentValue, type InstructionDocumentHandle } from '@/components/shared/instruction-document';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useReferenceLabels, useReferenceSearch } from '@/hooks/references-queries';
import type { AgentBrief, PromptMode } from '@/lib/types/domain';
import type { PublishBlocker, Ref } from '@/lib/types/references';

export const EMPTY_BRIEF: AgentBrief = { purpose: '', goal: '', howToAnswer: '', handOff: [], examples: '', never: [], success: [] };

/** The brief an agent without one starts from: its job line is the Job and its instructions are How to answer. */
export const legacyBrief = (a: { role: string; instructions: string }): AgentBrief => ({ ...EMPTY_BRIEF, purpose: a.role, howToAnswer: a.instructions });

// Five bands: Job, How to answer, Hand off when, Examples, Never. An agent that already has a Goal keeps it under Job;
// a new one is not asked for it. Success checks are not shown: they seed eval cases on the Evals tab.
const toValue = (b: AgentBrief, only: 'all' | 'never'): DocumentValue => ({
  blocks: [
    ...(only === 'all'
      ? ([
          { kind: 'field', key: 'brief.purpose', label: 'Job', locked: true, text: b.purpose, placeholder: 'What this agent is for and what a good outcome is, in a sentence or two. Type @ to name a tool, knowledge or skill.' },
          ...(b.goal.trim() ? ([{ kind: 'field', key: 'brief.goal', label: 'Goal', locked: true, text: b.goal, placeholder: 'Clear this to keep the outcome in Job.' }] as const) : []),
          { kind: 'field', key: 'brief.howToAnswer', label: 'How to answer', locked: true, text: b.howToAnswer, placeholder: 'Tone, order and what to include. Type @ to start a skill.' },
          { kind: 'list', key: 'brief.handOff', label: 'Hand off when', items: b.handOff, placeholder: 'A moment this agent passes the conversation to a person.' },
          { kind: 'field', key: 'brief.examples', label: 'Examples', locked: true, text: b.examples, placeholder: 'Optional. A question and the answer you want, as the person would see it.' },
        ] as const)
      : []),
    { kind: 'list', key: 'brief.never', label: 'Never', items: b.never, placeholder: 'Something this agent must never do. Applied last, on every reply.' },
  ],
});

const text = (v: DocumentValue, key: string) => v.blocks.flatMap((b) => (b.kind === 'field' && b.key === key ? [b.text] : [])).join('\n');
const list = (v: DocumentValue, key: string) => v.blocks.flatMap((b) => (b.kind === 'list' && b.key === key ? b.items : []));

/**
 * An agent's prompt as a brief: one card with a band per heading and `cardFooter` (the Uses counts and View prompt) as
 * its last row. An agent saved in plain text before the brief keeps its own text, with Never beside it, until it is
 * moved into the brief. The document is a view of the saved brief; `@` lists what the agent's team offers.
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
  cardFooter,
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
  /** The brief card's footer row: what the agent uses on the left, View prompt on the right. */
  cardFooter?: React.ReactNode;
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
        ? { ...brief, purpose: text(next, 'brief.purpose'), goal: text(next, 'brief.goal'), howToAnswer: text(next, 'brief.howToAnswer'), handOff: list(next, 'brief.handOff'), examples: text(next, 'brief.examples'), never: list(next, 'brief.never') }
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
        footerSlot={cardFooter}
        hint="Type @ to add a tool, knowledge, skill or agent"
      />
    </div>
  );
}

/** Shown only on an agent still in plain text: moves its text under How to answer, after the dialog shows the change. */
export function MoveIntoBrief({ onChoose, disabled }: { onChoose: () => void; disabled?: boolean }) {
  return (
    <Button type="button" variant="link" size="sm" className="self-start" disabled={disabled} onClick={onChoose} title="Move this text into the brief, under How to answer" data-testid="agent-prompt-mode">
      Use brief
    </Button>
  );
}
