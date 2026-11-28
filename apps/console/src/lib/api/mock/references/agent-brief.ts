import { composeHead } from '@/lib/brief-sections';
import { mentionsIn } from '@/lib/mentions';
import type { Agent, AgentBrief, InstructionSection } from '@/lib/types/domain';
import type { AgentPublishCheck, PublishBlocker } from '@/lib/types/references';

import { isOffered } from './index';

/** The prompt the service writes from a brief, for the all-mock console only: its headings in order, Never last. */
export const composeBrief = (name: string, b: AgentBrief, list: InstructionSection[]): string => composeHead(name, b, list);

/** The Never section the service writes after everything else, on every reply. */
export const neverSection = (b: AgentBrief | null | undefined): string => (b?.never.length ? `\n\n# Never\n${b.never.map((r) => `- ${r}`).join('\n')}` : '');

/** A brief the mock starts with: a card dispute desk that points at one tool, one knowledge base and one skill. */
export const SEED_BRIEF: AgentBrief = {
  purpose: 'Investigate card disputes with @tool:search_transactions and @knowledge:kb_card_disputes, and draft the outcome for a person to approve.',
  goal: 'Every dispute ends with a clear next step the cardholder can read in one message.',
  howToAnswer: 'Start with @skill:card_dispute. Say what you found, then what happens next, in plain words.',
  handOff: ['The cardholder asks for a person', 'The dispute is over 5,000'],
  examples: '',
  never: ['Promise a refund before the review is done', 'Ask for a full card number'],
  success: ['The cardholder knows what happens next', 'The evidence list is complete'],
  sections: [],
};

const FIELDS: [keyof AgentBrief, string][] = [
  ['purpose', 'Purpose'],
  ['goal', 'Goal'],
  ['howToAnswer', 'How to answer'],
  ['examples', 'Examples'],
];

/** What the publish check finds: an empty Purpose, and a reference the team no longer offers in the brief or, in full prompt mode, in the prompt. */
export function publishCheckOf(a: Pick<Agent, 'brief' | 'promptMode' | 'instructions'>): AgentPublishCheck {
  const problems: PublishBlocker[] = [];
  const b = a.brief;
  const missing = (field: string, text: string) => {
    for (const r of mentionsIn(text))
      if (!isOffered(`${r.kind}:${r.id}`)) problems.push({ kind: 'missing_reference', id: `${r.kind}:${r.id}`, position: { field, step: null, index: null }, message: `${r.id} is no longer offered to this team.` });
  };
  if (a.promptMode === 'full') missing('instructions', a.instructions);
  if (b) {
    if (!b.purpose.trim()) problems.push({ kind: 'missing_field', id: null, position: { field: 'brief.purpose', step: null, index: null }, message: 'Job is empty. Say what this agent is for.' });
    for (const [key] of FIELDS) missing(`brief.${key}`, String(b[key]));
  }
  return { canRequest: problems.length === 0, problems, blockers: problems.map((p) => ({ node: null, field: p.position?.field ?? null, level: 'error' as const, code: p.kind, message: p.message })) };
}
