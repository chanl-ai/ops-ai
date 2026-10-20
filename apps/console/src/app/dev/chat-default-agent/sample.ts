import type { ChatMessage } from '@/lib/types/chat';

export interface TeamAgent {
  id: string;
  name: string;
  role: string;
}

/** Operations' published agents. The first is the team default, provisioned with the workspace (c-175). */
export const AGENTS: TeamAgent[] = [
  { id: 'ag_ops_assistant', name: 'Operations Assistant', role: 'Answers from the team’s knowledge and asks a specialist when it needs one' },
  { id: 'ag_fraud', name: 'Fraud Specialist', role: 'Checks accounts, holds and wire activity' },
  { id: 'ag_policy', name: 'Policy Expert', role: 'Quotes the bank’s policies with citations' },
  { id: 'ag_levy', name: 'Levy Desk', role: 'Handles garnishment notices' },
];

const at = '2026-10-17T15:02:00Z';

/** The default agent answers and, for the account question, asks the Fraud Specialist as a tool (agent__ag_fraud). */
export const DEFAULT_THREAD: ChatMessage[] = [
  { id: 'm1', role: 'user', content: 'Is there a hold on account CHQ-2219, and can the customer still send a wire today?', at },
  {
    id: 'm2',
    role: 'assistant',
    content:
      'Yes. CHQ-2219 has a fraud hold placed this morning, so outgoing wires are blocked until it is cleared. I asked the Fraud Specialist, who found two declined wire attempts in the last hour. The daily wire limit for a personal account is $25,000 once the hold is lifted.',
    at,
    toolCalls: [
      {
        id: 't1',
        name: 'agent__ag_fraud',
        server: 'Fraud Specialist (agent)',
        input: { question: 'Is there a hold on CHQ-2219 and any recent wire attempts?' },
        output: { hold: 'fraud', placedAt: '09:14', wiresDeclined: 2 },
        status: 'success',
        durationMs: 2140,
      },
    ],
  },
];

/** After @Fraud Specialist, that agent answers the person directly until they go back. */
export const HANDED_OVER: ChatMessage[] = [
  { id: 'm3', role: 'user', content: '@Fraud Specialist what triggered the hold?', at },
  {
    id: 'm4',
    role: 'assistant',
    content: 'Two wire attempts to a new payee in under ten minutes, from a device the customer has not used before. The rule is “new payee velocity”; it clears when the customer confirms the payee by phone.',
    at,
  },
];
