import type { GrantScope } from '@/lib/types/governance';

/** Seed times are minutes before page load; the mock only runs in the browser. */
export const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
export const inDays = (d: number) => new Date(Date.now() + d * 86_400_000).toISOString();

/** Deterministic random numbers so every reload shows the same log. */
export function rng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) % 2147483648;
    return s / 2147483648;
  };
}

/** Tools reachable through the data gateway, by system. Includes the email workflow actions. */
export const MODULES: { tool: string; system: string; access: GrantScope }[] = [
  { tool: 'get_wire_history', system: 'Payments Hub', access: 'read' },
  { tool: 'place_wire_hold', system: 'Payments Hub', access: 'money_movement' },
  { tool: 'run_credit_check', system: 'Equifax', access: 'read' },
  { tool: 'verify_employment', system: 'The Work Number', access: 'read' },
  { tool: 'issue_preapproval', system: 'Loan Origination', access: 'write' },
  { tool: 'screen_watchlists', system: 'Compliance MCP', access: 'read' },
  { tool: 'corporate_registry', system: 'Compliance MCP', access: 'read' },
  { tool: 'get_transactions', system: 'Card Platform', access: 'read' },
  { tool: 'issue_provisional_credit', system: 'Card Platform', access: 'money_movement' },
  { tool: 'waive_fee', system: 'Card Platform', access: 'write' },
  { tool: 'search_knowledge', system: 'Data Hub', access: 'read' },
  { tool: 'book_appointment', system: 'Branch Scheduler', access: 'write' },
  { tool: 'transfer_funds', system: 'Core Banking', access: 'money_movement' },
  { tool: 'update_address', system: 'Core Banking', access: 'write' },
  { tool: 'get_loan_account', system: 'Core Banking', access: 'read' },
  { tool: 'apply_payment_deferral', system: 'Core Banking', access: 'write' },
  { tool: 'send_reply', system: 'Outbound mail', access: 'write' },
];

export const moduleOf = (tool: string) => MODULES.find((m) => m.tool === tool)!;
export const moduleLabel = (tool: string) => `${moduleOf(tool).system} · ${tool}`;

export const KB_IDS: Record<string, string> = {
  'Fraud & payments': 'kb_people',
  Compliance: 'kb_eng',
  'Retail banking': 'kb_support',
  'Lending policy': 'kb_lending',
  'Cards & disputes': 'kb_legal',
  'All bank knowledge': 'kb_all',
};

/** What each workflow's identity is granted: the tools its agents call and the knowledge bases they cite. */
export const WORKFLOW_ACCESS: Record<string, { tools: string[]; kbs: string[] }> = {
  wf_wire: { tools: ['get_wire_history', 'search_knowledge', 'place_wire_hold'], kbs: ['Fraud & payments', 'Compliance'] },
  wf_mortgage: { tools: ['run_credit_check', 'verify_employment', 'search_knowledge', 'issue_preapproval', 'corporate_registry'], kbs: ['Lending policy'] },
  wf_dispute: { tools: ['get_transactions', 'search_knowledge', 'issue_provisional_credit'], kbs: ['Cards & disputes'] },
  wf_kyb: { tools: ['corporate_registry', 'screen_watchlists', 'search_knowledge'], kbs: ['Compliance'] },
  wf_branch_chat: { tools: ['search_knowledge', 'book_appointment'], kbs: ['Retail banking'] },
  wf_card_inbox: { tools: ['get_transactions', 'issue_provisional_credit', 'waive_fee', 'update_address', 'send_reply'], kbs: ['Cards & disputes'] },
  wf_lending_inbox: { tools: ['get_loan_account', 'apply_payment_deferral', 'update_address', 'send_reply'], kbs: ['Lending policy'] },
  wf_advisor: { tools: [], kbs: [] },
};

export const principalOf = (workflowName: string) => `wf.${workflowName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}@ops.northfieldbank.com`;

/** Model aliases the AI gateway resolves; agents name a model, runs call it through its alias. */
export const MODEL_ALIAS: Record<string, { alias: string; inPerM: number; outPerM: number }> = {
  'claude-haiku-4-5': { alias: 'ops-fast', inPerM: 1.4, outPerM: 6.8 },
  'claude-sonnet-5': { alias: 'ops-reasoning', inPerM: 4.1, outPerM: 20.5 },
  'claude-opus-5-5': { alias: 'ops-deep', inPerM: 6.8, outPerM: 34 },
};

/** Gate policy versions in force; the fixtures carry no versions, so the log pins these. */
export const POLICY_VERSION: Record<string, number> = { gp_1: 4, gp_2: 2, gp_3: 6, gp_5: 3, gp_7: 5, gp_9: 1 };

export const PEOPLE = ['James Richardson', 'Maya Okafor', 'Anika Singh', 'Daniel Brooks', 'Priya Shah', 'Tom Haddad', 'Lena Fischer', 'Omar Siddiqui', 'Grace Liu', 'Rafael Costa'];
export const emailOf = (name: string) => `${name.split(' ')[0][0].toLowerCase()}.${name.split(' ').slice(-1)[0].toLowerCase()}@northfieldbank.com`;
