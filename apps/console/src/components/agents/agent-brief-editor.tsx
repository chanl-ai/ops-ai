'use client';

import * as React from 'react';

import { parseText } from '@/components/shared/instruction-document/document-model';
import { InstructionDocument, referencesIn, type Block, type DocumentValue, type InstructionDocumentHandle } from '@/components/shared/instruction-document';
import { CUSTOM_ID, CUSTOM_NAME_MAX, offeredSections, placesOf, sectionProblem, titled } from '@/lib/brief-sections';
import { CUSTOM_PLACEHOLDER, SECTION_PLACEHOLDER } from '@/components/agents/brief-headings';
import { FormField } from '@/components/shared/form-field';
import { GroupedPicker, type PickerGroup, type PickerItem } from '@/components/shared/grouped-picker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RichTextEditor } from '@/components/shared/rich-text-editor';
import { useInstructionSections } from '@/hooks/instruction-sections';
import { useReferenceLabels, useReferenceSearch } from '@/hooks/references-queries';
import type { AgentBrief, BriefSection, InstructionSection, InstructionSectionList, PromptMode } from '@/lib/types/domain';
import type { PublishBlocker, Ref } from '@/lib/types/references';

export const EMPTY_BRIEF: AgentBrief = { purpose: '', goal: '', howToAnswer: '', handOff: [], examples: '', never: [], success: [] };

/** The brief an agent without one starts from: its job line is the Job and its instructions are How to answer. */
export const legacyBrief = (a: { role: string; instructions: string }): AgentBrief => ({ ...EMPTY_BRIEF, purpose: a.role, howToAnswer: a.instructions });

// The brief's bands in the order the workspace's list writes the prompt: Purpose (shown as Job), Goal when it is set,
// How to answer, Hand off when and Examples, with the sections a builder added at their list entry's place. Never is
// always the last band. Success checks are not shown: they seed eval cases on the Evals tab.
const SECTION_KEY = 'brief.sections.';
const sectionKey = (kind: string, customIndex: number) => (kind === CUSTOM_ID ? `${SECTION_KEY}custom.${customIndex}` : `${SECTION_KEY}${kind}`);

// Until the workspace's list is read, the brief's own fields keep their usual order and its sections follow them.
const FIELD_ORDER: InstructionSection[] = ['purpose', 'goal', 'how_to_answer', 'hand_off', 'examples'].map((id, order) => ({ id, label: id, hint: '', kind: 'fixed', order, required: false, hidden: false, drives: 'none', group: '', example: '', presets: [] }));

const toValue = (b: AgentBrief, only: 'all' | 'never', list: InstructionSection[]): DocumentValue => {
  const fields: Record<string, Block> = {
    purpose: { kind: 'field', key: 'brief.purpose', label: 'Job', locked: true, text: b.purpose, placeholder: 'What this agent is for and what a good outcome is, in a sentence or two. Type @ to name a tool, knowledge or skill.' },
    goal: { kind: 'field', key: 'brief.goal', label: 'Goal', locked: true, text: b.goal, placeholder: 'Clear this to keep the outcome in Job.' },
    how_to_answer: { kind: 'field', key: 'brief.howToAnswer', label: 'How to answer', locked: true, text: b.howToAnswer, placeholder: 'What to include in an answer, and how to format it. Type @ to start a skill.' },
    hand_off: { kind: 'list', key: 'brief.handOff', label: 'Hand off when', optional: true, items: b.handOff, placeholder: 'A moment this agent passes the conversation to a person.' },
    examples: { kind: 'field', key: 'brief.examples', label: 'Examples', optional: true, locked: true, text: b.examples, placeholder: 'Optional. A question and the answer you want, as the person would see it.' },
  };
  // An agent with a Goal keeps it under Job; a new one is not asked for it.
  const shown = (id: string) => id !== 'goal' || b.goal.trim() !== '';
  const blocks: Block[] = [];
  for (const place of placesOf(list.length ? list : FIELD_ORDER, b.sections ?? [])) {
    if (place.at === 'field') {
      if (fields[place.id] && shown(place.id)) blocks.push(fields[place.id]);
    } else {
      const s = place.section;
      const custom = s.kind === CUSTOM_ID;
      blocks.push({
        kind: 'field',
        key: sectionKey(s.kind, place.custom),
        label: custom ? s.name : (place.item?.label ?? s.name),
        locked: true,
        removable: true,
        text: s.text,
        placeholder: custom ? CUSTOM_PLACEHOLDER : place.item?.example ? `e.g. ${place.item.example}` : SECTION_PLACEHOLDER,
        ...(custom ? { note: 'prompt text only' } : {}),
        ...(place.item?.presets.length ? { chips: place.item.presets } : {}),
      });
    }
  }
  return {
    blocks: [
      ...(only === 'all' ? blocks : []),
      { kind: 'list', key: 'brief.never', label: 'Never · applied last, on every reply', optional: true, items: b.never, placeholder: 'Something this agent must never do. Applied last, on every reply.' },
    ],
  };
};

/** The sections the document holds, in its order, as the brief stores them. */
const sectionsIn = (v: DocumentValue, list: InstructionSection[]): BriefSection[] =>
  v.blocks.flatMap((b): BriefSection[] => {
    if (b.kind !== 'field' || !b.key.startsWith(SECTION_KEY)) return [];
    const rest = b.key.slice(SECTION_KEY.length);
    if (rest.startsWith('custom.')) return [{ kind: CUSTOM_ID, name: b.label, text: b.text }];
    return [{ kind: rest, name: list.find((i) => i.id === rest)?.label ?? b.label, text: b.text }];
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
}) {
  const context = React.useMemo(() => ({ forAgent: agentId }), [agentId]);
  const only = mode === 'full' ? 'never' : 'all';
  const listQuery = useInstructionSections();
  const workspace: InstructionSectionList | undefined = listQuery.data;
  const entries = React.useMemo(() => workspace?.sections ?? [], [workspace]);
  const document = React.useMemo(() => toValue(brief, only, entries), [brief, only, entries]);
  const ids = React.useMemo(() => referencesIn(document).map((r) => `${r.kind}:${r.id}`), [document]);
  const labels = useReferenceLabels(context, ids);
  // The plain-text prompt's own mentions, named the same way.
  const textIds = React.useMemo(() => [...new Set(parseText(instructions).flatMap((x) => (x.t === 'ref' ? [`${x.kind}:${x.id}`] : [])))], [instructions]);
  const textLabels = useReferenceLabels(context, textIds);
  const search = useReferenceSearch(context);
  const invalid = React.useMemo(
    () =>
      (problems ?? [])
        .filter((p) => p.kind !== 'missing_reference' && p.position?.field.startsWith('brief.'))
        .map((p) => ({ field: p.position!.field === 'brief.sections' ? sectionFieldAt(brief.sections ?? [], p.position!.index, entries) : p.position!.field, message: p.message })),
    [problems, brief.sections],
  );
  const onChange = (next: DocumentValue) =>
    onBrief(
      only === 'all'
        ? { ...brief, purpose: text(next, 'brief.purpose'), goal: text(next, 'brief.goal'), howToAnswer: text(next, 'brief.howToAnswer'), handOff: list(next, 'brief.handOff'), examples: text(next, 'brief.examples'), never: list(next, 'brief.never'), sections: sectionsIn(next, entries) }
        : { ...brief, never: list(next, 'brief.never') },
    );
  const sections = brief.sections ?? [];
  const addSection = (section: BriefSection) => onBrief({ ...brief, sections: [...sections, titled(section, entries)] });
  const removeSection = (key: string) => {
    // The document lists sections in the order the prompt writes them; what is left keeps that order.
    const keys = document.blocks.flatMap((b) => (b.kind === 'field' && b.key.startsWith(SECTION_KEY) ? [b.key] : []));
    onBrief({ ...brief, sections: sectionsIn(document, entries).filter((_, i) => keys[i] !== key) });
  };
  // A preset is ordinary text: it replaces a section that is empty or still holds a preset's sentence, and is added as
  // a new line to anything the builder has written.
  const pickChip = (key: string, sentence: string) => {
    const kind = key.slice(SECTION_KEY.length);
    const presets = entries.find((i) => i.id === kind)?.presets ?? [];
    onBrief({
      ...brief,
      sections: sectionsIn(document, entries).map((s) => {
        if (s.kind !== kind) return s;
        const own = s.text.trim() === '' || presets.some((p) => p.text.trim() === s.text.trim());
        return { ...s, text: own ? sentence : `${s.text.trimEnd()}\n${sentence}` };
      }),
    });
  };
  return (
    <div className="flex flex-col gap-3" data-testid="agent-brief">
      {mode === 'full' && (
        <div className="flex flex-col gap-2">
          {toolbar && <div className="flex flex-wrap justify-end gap-2">{toolbar}</div>}
          <div className="rounded-lg border bg-card" data-testid="agent-plain-text">
            <RichTextEditor value={instructions} onChange={onInstructions} readOnly={readOnly} context={context} labels={textLabels.data} ariaLabel="Instructions" />
          </div>
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
        onChip={mode === 'brief' ? pickChip : undefined}
        belowSlot={mode === 'brief' ? <AddSection sections={sections} workspace={workspace} state={{ loading: listQuery.isPending, error: listQuery.isError, retry: () => void listQuery.refetch() }} onAdd={addSection} /> : undefined}
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
function sectionFieldAt(sections: readonly BriefSection[], index: number | null | undefined, list: InstructionSection[]): string {
  void list;
  const target = index == null ? undefined : sections[index];
  return target ? sectionKey(target.kind, sections.filter((s) => s.kind === CUSTOM_ID).indexOf(target)) : 'brief.sections';
}

/**
 * Add section: a searchable list of the workspace's sections in the groups the list gives them, each with its example
 * line, then a section of the builder's own, named here first. One already added is greyed out and checked. The name
 * is checked as the service checks it, and its message stays beside the field.
 */
function AddSection({ sections, workspace, state, onAdd }: { sections: readonly BriefSection[]; workspace: InstructionSectionList | undefined; state: { loading: boolean; error: boolean; retry: () => void }; onAdd: (s: BriefSection) => void }) {
  const [naming, setNaming] = React.useState(false);
  const [name, setName] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const nameId = React.useId();
  const entries = workspace?.sections ?? [];
  const customMax = workspace?.customMax ?? 0;
  const own = sections.filter((s) => s.kind === CUSTOM_ID);
  const atLimit = own.length >= customMax;
  // Groups in the order their first section appears; a section an admin added has no group and joins Your sections,
  // which also holds Add custom section.
  const offered = offeredSections(entries);
  const item = (i: InstructionSection): PickerItem => ({ value: i.id, label: i.label, description: i.example, disabled: sections.some((s) => s.kind === i.id), checked: sections.some((s) => s.kind === i.id), testId: `agent-add-section-${i.id}` });
  const groups = offered
    .filter((i) => i.group)
    .reduce<PickerGroup[]>((acc, i) => {
      const found = acc.find((g) => g.heading === i.group);
      if (found) found.items.push(item(i));
      else acc.push({ heading: i.group, items: [item(i)] });
      return acc;
    }, []);
  const ownItems = offered.filter((i) => !i.group).map(item);
  const customEntry = entries.find((i) => i.id === CUSTOM_ID);
  if (ownItems.length || customEntry)
    groups.push({
      heading: 'Your sections',
      items: [...ownItems, ...(customEntry ? [{ value: CUSTOM_ID, label: 'Add custom section', description: atLimit ? `An agent may have at most ${customMax} sections of its own.` : 'Your own heading, written into the prompt', disabled: atLimit, testId: 'agent-add-section-custom' }] : [])],
    });
  const close = () => {
    setNaming(false);
    setName('');
    setError(null);
  };
  const addNamed = () => {
    const trimmed = name.trim();
    if (!trimmed) return setError('Give the section a name.');
    const next: BriefSection = { kind: CUSTOM_ID, name: trimmed, text: '' };
    const problem = sectionProblem([...sections, next], entries, customMax);
    if (problem) return setError(problem.replace(/^brief\.sections: /, ''));
    onAdd(next);
    close();
  };
  return (
    <div className="flex flex-col gap-2" data-testid="agent-add-section">
      <div className="flex flex-wrap items-center gap-2">
        <GroupedPicker
          label="Add section"
          searchPlaceholder="Search sections"
          testId="agent-add-section-menu"
          groups={groups}
          state={state.loading ? 'loading' : state.error || !workspace ? 'error' : 'ready'}
          onRetry={state.retry}
          emptyText="No section matches."
          onPick={(value) => {
            if (value === CUSTOM_ID) setNaming(true);
            else onAdd({ kind: value, name: entries.find((i) => i.id === value)?.label ?? value, text: '' });
          }}
        />
        {atLimit && customMax > 0 && !naming && <span className="text-xs text-muted-foreground">An agent may have at most {customMax} sections of its own.</span>}
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
