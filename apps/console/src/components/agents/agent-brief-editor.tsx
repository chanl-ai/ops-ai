'use client';

import * as React from 'react';

import { InstructionDocument, referencesIn, type Block, type DocumentValue, type InstructionDocumentHandle } from '@/components/shared/instruction-document';
import { AddMenu } from '@/components/shared/add-menu';
import { CUSTOM_MAX, CUSTOM_NAME_MAX, SECTION_TITLES, placeSections, sectionProblem, titled } from '@/lib/brief-sections';
import { CUSTOM_PLACEHOLDER, SECTION_COPY } from '@/components/agents/brief-headings';
import { FormField } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useInstructionSections, type InstructionSectionItem } from '@/hooks/instruction-sections';
import { useReferenceLabels, useReferenceSearch } from '@/hooks/references-queries';
import type { AgentBrief, BriefSection, MenuSectionKind, PromptMode } from '@/lib/types/domain';
import type { PublishBlocker, Ref } from '@/lib/types/references';

export const EMPTY_BRIEF: AgentBrief = { purpose: '', goal: '', howToAnswer: '', handOff: [], examples: '', never: [], success: [] };

/** The brief an agent without one starts from: its job line is the Job and its instructions are How to answer. */
export const legacyBrief = (a: { role: string; instructions: string }): AgentBrief => ({ ...EMPTY_BRIEF, purpose: a.role, howToAnswer: a.instructions });

// Fixed bands: Job, How to answer, Hand off when, Examples, Never. An agent that already has a Goal keeps it under Job;
// a new one is not asked for it. Success checks are not shown: they seed eval cases on the Evals tab. Sections the
// builder added sit in the order the prompt writes them (`placeSections`): Personality to Context before How to answer,
// Tool use, Error handling and the builder's own after it, Escalation wording straight after Hand off when.
const SECTION_KEY = 'brief.sections.';
const sectionKey = (kind: BriefSection['kind'], customIndex: number) => (kind === 'custom' ? `${SECTION_KEY}custom.${customIndex}` : `${SECTION_KEY}${kind}`);
const sectionBlock = (s: BriefSection, key: string): Block => ({
  kind: 'field',
  key,
  label: s.name,
  locked: true,
  removable: true,
  text: s.text,
  placeholder: s.kind === 'custom' ? CUSTOM_PLACEHOLDER : SECTION_COPY[s.kind].placeholder,
  ...(s.kind === 'custom' ? { note: 'prompt text only' } : {}),
});

const toValue = (b: AgentBrief, only: 'all' | 'never'): DocumentValue => {
  const { beforeHow, afterHow, afterHandOff } = placeSections(b.sections ?? []);
  let custom = 0;
  const blocks = (list: BriefSection[]) => list.map((s) => sectionBlock(s, sectionKey(s.kind, s.kind === 'custom' ? custom++ : 0)));
  return {
    blocks: [
      ...(only === 'all'
        ? ([
            { kind: 'field', key: 'brief.purpose', label: 'Job', locked: true, text: b.purpose, placeholder: 'What this agent is for and what a good outcome is, in a sentence or two. Type @ to name a tool, knowledge or skill.' },
            ...(b.goal.trim() ? ([{ kind: 'field', key: 'brief.goal', label: 'Goal', locked: true, text: b.goal, placeholder: 'Clear this to keep the outcome in Job.' }] as const) : []),
            ...blocks(beforeHow),
            { kind: 'field', key: 'brief.howToAnswer', label: 'How to answer', locked: true, text: b.howToAnswer, placeholder: 'What to include in an answer, and how to format it. Type @ to start a skill.' },
            ...blocks(afterHow),
            { kind: 'list', key: 'brief.handOff', label: 'Hand off when', optional: true, items: b.handOff, placeholder: 'A moment this agent passes the conversation to a person.' },
            ...blocks(afterHandOff),
            { kind: 'field', key: 'brief.examples', label: 'Examples', optional: true, locked: true, text: b.examples, placeholder: 'Optional. A question and the answer you want, as the person would see it.' },
          ] as Block[])
        : []),
      { kind: 'list', key: 'brief.never', label: 'Never · applied last, on every reply', optional: true, items: b.never, placeholder: 'Something this agent must never do. Applied last, on every reply.' },
    ],
  };
};

/** The sections the document holds, in its order, as the brief stores them. */
const sectionsIn = (v: DocumentValue): BriefSection[] =>
  v.blocks.flatMap((b): BriefSection[] => {
    if (b.kind !== 'field' || !b.key.startsWith(SECTION_KEY)) return [];
    const rest = b.key.slice(SECTION_KEY.length);
    return rest.startsWith('custom.') ? [{ kind: 'custom', name: b.label, text: b.text }] : [{ kind: rest as MenuSectionKind, name: SECTION_TITLES[rest as MenuSectionKind], text: b.text }];
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
  cardHeader,
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
  /** The brief card's header actions (Draft); not shown while the agent is plain text. */
  cardHeader?: React.ReactNode;
  textareaRef?: React.Ref<HTMLTextAreaElement>;
}) {
  const context = React.useMemo(() => ({ forAgent: agentId }), [agentId]);
  const only = mode === 'full' ? 'never' : 'all';
  const document = React.useMemo(() => toValue(brief, only), [brief, only]);
  const ids = React.useMemo(() => referencesIn(document).map((r) => `${r.kind}:${r.id}`), [document]);
  const labels = useReferenceLabels(context, ids);
  const search = useReferenceSearch(context);
  const invalid = React.useMemo(
    () =>
      (problems ?? [])
        .filter((p) => p.kind !== 'missing_reference' && p.position?.field.startsWith('brief.'))
        .map((p) => ({ field: p.position!.field === 'brief.sections' ? sectionFieldAt(brief.sections ?? [], p.position!.index) : p.position!.field, message: p.message })),
    [problems, brief.sections],
  );
  const onChange = (next: DocumentValue) =>
    onBrief(
      only === 'all'
        ? { ...brief, purpose: text(next, 'brief.purpose'), goal: text(next, 'brief.goal'), howToAnswer: text(next, 'brief.howToAnswer'), handOff: list(next, 'brief.handOff'), examples: text(next, 'brief.examples'), never: list(next, 'brief.never'), sections: sectionsIn(next) }
        : { ...brief, never: list(next, 'brief.never') },
    );
  const offered = useInstructionSections();
  const sections = brief.sections ?? [];
  const addSection = (section: BriefSection) => onBrief({ ...brief, sections: [...sections, titled(section)] });
  const removeSection = (key: string) => {
    // The document lists sections in the order the prompt writes them; what is left keeps that order.
    const keys = document.blocks.flatMap((b) => (b.kind === 'field' && b.key.startsWith(SECTION_KEY) ? [b.key] : []));
    onBrief({ ...brief, sections: sectionsIn(document).filter((_, i) => keys[i] !== key) });
  };
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
        headerSlot={cardHeader}
        onRemoveBlock={mode === 'brief' ? removeSection : undefined}
        belowSlot={mode === 'brief' ? <AddSection sections={sections} offered={offered} onAdd={addSection} /> : undefined}
        showHint={false}
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

/** The block key of the section a publish problem names by its place among the sections, or the brief's sections as a whole. */
function sectionFieldAt(sections: readonly BriefSection[], index: number | null | undefined): string {
  const target = index == null ? undefined : sections[index];
  return target ? sectionKey(target.kind, sections.filter((s) => s.kind === 'custom').indexOf(target)) : 'brief.sections';
}

/**
 * Add section: the seven sections of the menu (one already added is greyed out), then a section of the builder's own,
 * named here first. The name is checked as the service checks it, and its message stays beside the field.
 */
function AddSection({ sections, offered, onAdd }: { sections: readonly BriefSection[]; offered: InstructionSectionItem[]; onAdd: (s: BriefSection) => void }) {
  const [naming, setNaming] = React.useState(false);
  const [name, setName] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const nameId = React.useId();
  const own = sections.filter((s) => s.kind === 'custom');
  const atLimit = own.length >= CUSTOM_MAX;
  const close = () => {
    setNaming(false);
    setName('');
    setError(null);
  };
  const addNamed = () => {
    const trimmed = name.trim();
    if (!trimmed) return setError('Give the section a name.');
    const next: BriefSection = { kind: 'custom', name: trimmed, text: '' };
    const problem = sectionProblem([...sections, next]);
    if (problem) return setError(problem.replace(/^brief\.sections: /, ''));
    onAdd(next);
    close();
  };
  return (
    <div className="flex flex-col gap-2" data-testid="agent-add-section">
      <div className="flex flex-wrap items-center gap-2">
        <AddMenu
          label="Add section"
          align="start"
          testId="agent-add-section-menu"
          onSelect={(v) => (v === 'custom' ? setNaming(true) : onAdd({ kind: v as MenuSectionKind, name: SECTION_TITLES[v as MenuSectionKind], text: '' }))}
          items={[
            ...offered.map((o) => ({ value: o.id, label: o.title, disabled: sections.some((s) => s.kind === o.id), testId: `agent-add-section-${o.id}` })),
            { value: 'custom', label: 'Add custom section', disabled: atLimit, group: 'Your own', testId: 'agent-add-section-custom' },
          ]}
        />
        {atLimit && !naming && <span className="text-xs text-muted-foreground">An agent may have at most {CUSTOM_MAX} sections of its own.</span>}
      </div>
      {naming && (
        <div className="flex flex-wrap items-start gap-2">
          <FormField id={nameId} label="Section name" hint="Prompt text only: nothing else reads this section." error={error ?? undefined} className="min-w-0 flex-1 basis-56">
            <Input
              id={nameId}
              value={name}
              autoFocus
              maxLength={CUSTOM_NAME_MAX + 20}
              placeholder="e.g. Refund wording"
              aria-invalid={error ? true : undefined}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addNamed();
                } else if (e.key === 'Escape') {
                  e.stopPropagation();
                  close();
                }
              }}
            />
          </FormField>
          <div className="flex gap-2 pt-6">
            <Button type="button" size="sm" onClick={addNamed}>
              Add
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={close}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
