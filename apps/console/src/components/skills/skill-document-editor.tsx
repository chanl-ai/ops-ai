'use client';

import * as React from 'react';

import { InstructionDocument, referencesIn, type DocumentValue, type InstructionDocumentHandle, type StepValue } from '@/components/shared/instruction-document';
import { useReferenceLabels, useReferenceSearch } from '@/hooks/references-queries';
import type { PublishBlocker } from '@/lib/types/references';

import { NOTES, placeProblems } from './skill-problems';

export interface SkillDocument {
  instructions: string;
  steps: StepValue[];
}

const toValue = (doc: SkillDocument): DocumentValue => ({
  blocks: [
    { kind: 'field', key: NOTES, label: 'Notes for every step', locked: true, text: doc.instructions, placeholder: 'What holds for the whole skill: tone, rules, what to hand back.' },
    { kind: 'steps', steps: doc.steps, placeholder: 'Describe the first step. Type @ to name a tool, a knowledge base or another skill.' },
  ],
});

const fromValue = (value: DocumentValue): SkillDocument => ({
  instructions: value.blocks.flatMap((b) => (b.kind === 'field' && b.key === NOTES ? [b.text] : [])).join('\n'),
  steps: value.blocks.flatMap((b) => (b.kind === 'steps' ? b.steps : [])),
});

/**
 * A skill's notes and numbered steps as one document. The document is a view of the stored `instructions` and
 * `steps`; the `@` menu lists what the skill's team offers, and a chip shows the current name of what it points at.
 */
export function SkillDocumentEditor({
  skillId,
  name,
  value,
  onChange,
  readOnly,
  problems,
  controls,
}: {
  skillId: string;
  name: string;
  value: SkillDocument;
  onChange: (next: SkillDocument) => void;
  readOnly?: boolean;
  /** The publish check's problems and a refused save's; one on a step is shown under that step. */
  problems?: PublishBlocker[];
  /** Moves the caret to a step, for a problem's "Go to step" link. */
  controls?: React.Ref<InstructionDocumentHandle>;
}) {
  const context = React.useMemo(() => ({ forSkill: skillId }), [skillId]);
  const document = React.useMemo(() => toValue(value), [value]);
  const ids = React.useMemo(() => referencesIn(document).map((r) => `${r.kind}:${r.id}`), [document]);
  const labels = useReferenceLabels(context, ids);
  const search = useReferenceSearch(context);
  const invalid = React.useMemo(() => placeProblems(problems ?? []), [problems]);
  return (
    <div data-testid="skill-document">
      <InstructionDocument
        label={`${name} steps`}
        value={document}
        onChange={(next) => onChange(fromValue(next))}
        searchReferences={search}
        resolved={labels.data}
        missing={problems}
        invalid={invalid}
        controls={controls}
        readOnly={readOnly}
        footer="add-step"
        hint="Type @ to add a tool, knowledge or skill"
      />
    </div>
  );
}
