import { composeHead } from '@/lib/brief-sections';
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

const TOKEN = /@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9_.-]*[A-Za-z0-9_])/g;
const FIELDS: [keyof AgentBrief, string][] = [
  ['purpose', 'Purpose'],
  ['goal', 'Goal'],
  ['howToAnswer', 'How to answer'],
  ['examples', 'Examples'],
];

/** What the publish check finds in a brief agent: an empty Purpose, and a reference the team no longer offers. */
export function publishCheckOf(a: Pick<Agent, 'brief' | 'promptMode'>): AgentPublishCheck {
  const problems: PublishBlocker[] = [];
  const b = a.brief;
  if (b) {
    if (!b.purpose.trim()) problems.push({ kind: 'missing_field', id: null, position: { field: 'brief.purpose', step: null, index: null }, message: 'Job is empty. Say what this agent is for.' });
    for (const [key] of FIELDS)
      for (const m of String(b[key]).matchAll(TOKEN))
        if (!isOffered(`${m[1]}:${m[2]}`)) problems.push({ kind: 'missing_reference', id: `${m[1]}:${m[2]}`, position: { field: `brief.${key}`, step: null, index: null }, message: `${m[2]} is no longer offered to this team.` });
  }
  return { canRequest: problems.length === 0, problems, blockers: problems.map((p) => ({ node: null, field: p.position?.field ?? null, level: 'error' as const, code: p.kind, message: p.message })) };
}
