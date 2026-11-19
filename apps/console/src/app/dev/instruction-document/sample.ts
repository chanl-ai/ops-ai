import type { DocumentValue, VariableGroup } from '@/components/shared/instruction-document';
import type { PublishBlocker } from '@/lib/types/references';

/** An agent's brief. `refund_card` is a tool the team no longer has, so its chip reads Missing. */
export const BRIEF: DocumentValue = {
  blocks: [
    { kind: 'field', key: 'brief.purpose', label: 'Purpose', locked: true, text: 'Settles card disputes under 500 dollars the same day.', placeholder: 'Say what this agent settles, for whom, and the limit.' },
    { kind: 'field', key: 'brief.goal', label: 'Goal', locked: true, text: '', placeholder: 'What the person knows at the end.' },
    {
      kind: 'field',
      key: 'brief.howToAnswer',
      label: 'How to answer',
      locked: true,
      text: 'Greet {{customer.first_name}} and check the case with @tool:search_transactions.\nAnswer only from @knowledge:kb_card_disputes and name the source. Refund with @tool:refund_card.',
      placeholder: 'Type @ to add a tool, knowledge or skill.',
    },
    { kind: 'list', key: 'brief.never', label: 'Never', items: ['Promise a refund before @skill:verify_identity passes.', 'Read out a full card number.'], placeholder: 'The things this agent must not do.' },
    { kind: 'list', key: 'brief.success', label: 'Success checks', items: [], placeholder: 'What a good answer does.' },
  ],
};

export const BRIEF_PROBLEMS: PublishBlocker[] = [
  { kind: 'missing_reference', id: 'tool:refund_card', position: { field: 'brief.howToAnswer', step: null, index: null }, message: 'Dispute desk no longer has “refund_card”.' },
];

/** A skill: notes for every step, then the steps. */
export const SKILL: DocumentValue = {
  blocks: [
    { kind: 'field', key: 'instructions', label: 'Notes for every step', locked: true, text: 'Keep each answer to two sentences.', placeholder: 'What holds for every step. Optional.' },
    {
      kind: 'steps',
      placeholder: 'Write the first step. Type @ to add a tool, knowledge or skill.',
      steps: [
        { do: 'List the papers the loan file still lacks.', use: { kind: 'tool', id: 'loan_file_lookup' } },
        { do: 'Confirm who {{customer.name}} is with @skill:verify_identity.', check: { text: 'result.verified == true', by: 'rule' }, ifNot: { action: 'exit', exit: 'failed' } },
        { do: 'Tell the officer what is still missing.', check: { text: 'The officer has the full list', by: 'model' }, ifNot: { action: 'goto', step: 2 } },
      ],
    },
  ],
};

export const VARIABLES: VariableGroup[] = [
  { label: 'Customer', items: [{ name: 'customer.name', sample: 'Dana Whitfield' }, { name: 'customer.first_name', sample: 'Dana' }, { name: 'customer.card_last4', sample: '4821' }] },
  { label: 'Case', items: [{ name: 'case.number', sample: 'CD-20418' }] },
];
