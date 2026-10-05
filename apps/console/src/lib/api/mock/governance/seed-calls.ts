import type { CallApproval, CallOperation, CallStatus, ToolCallDetail } from '@/lib/types/governance';

import * as F from '../fixtures';
import { MODEL_ALIAS, minsAgo, moduleLabel, moduleOf, POLICY_VERSION, principalOf, rng, WORKFLOW_ACCESS } from './catalog';

const MASK = '[redacted]';

interface Payload {
  record?: string;
  amount?: number;
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  redacted: string[];
}

const CUSTOMERS = ['Hartwell Dental Corp', 'Sarah Chen', 'Lin & Moreau LLP', 'Priya Natarajan', 'Northgate Logistics Inc.', 'Marcus Webb', 'Grace Kim', 'Tomás Alvarez', 'Coastal Imports Ltd.', 'Elena Vasquez'];

/** Representative request and response for each tool; customer identifiers are masked the way the gateway stores them. */
const PAYLOADS: Record<string, (r: () => number, i: number) => Payload> = {
  get_wire_history: (r, i) => ({
    record: `Account ••${4417 + i}`,
    request: { accountId: MASK, days: 3 },
    response: { attempts: 1 + Math.floor(r() * 3), mfa: r() > 0.2 ? 'passed' : 'stepped_up', lastPayee: { name: MASK, ageHours: Math.floor(r() * 200) } },
    redacted: ['request.accountId', 'response.lastPayee.name'],
  }),
  place_wire_hold: (r, i) => {
    const amount = Math.round(20_000 + r() * 160_000);
    return {
      record: `Wire W-${88200 + i}`,
      amount,
      request: { wireId: `W-${88200 + i}`, action: 'hold', hours: 24, amount },
      response: { held: true, releaseAt: minsAgo(-60 * 24), callbackRequired: true },
      redacted: [],
    };
  },
  run_credit_check: (r) => ({
    record: `Application APP-${40900 + Math.floor(r() * 90)}`,
    request: { applicantId: MASK, bureau: 'Equifax', consentRef: 'CNS-2291' },
    response: { score: 640 + Math.floor(r() * 180), tradelines: 4 + Math.floor(r() * 9), inquiries90d: Math.floor(r() * 4) },
    redacted: ['request.applicantId'],
  }),
  verify_employment: (r) => ({
    record: `Application APP-${40900 + Math.floor(r() * 90)}`,
    request: { applicantId: MASK, employer: 'Lakeshore Health', sin: MASK },
    response: { employed: true, tenureMonths: 12 + Math.floor(r() * 90), annualIncome: MASK },
    redacted: ['request.applicantId', 'request.sin', 'response.annualIncome'],
  }),
  issue_preapproval: (r) => {
    const amount = Math.round(280_000 + r() * 520_000);
    return {
      record: `Application APP-${40900 + Math.floor(r() * 90)}`,
      amount,
      request: { applicationId: `APP-${40900 + Math.floor(r() * 90)}`, amount, rate: 5.24, termYears: 25 },
      response: { preapprovalId: `PA-${7000 + Math.floor(r() * 900)}`, validUntil: minsAgo(-60 * 24 * 90) },
      redacted: [],
    };
  },
  screen_watchlists: (r) => ({
    record: `Business ${['Aurelia Holdings', 'Brightline Studio', 'Northgate Logistics Inc.'][Math.floor(r() * 3)]}`,
    request: { name: MASK, country: 'CA', lists: ['PEP', 'OFAC', 'UN', 'adverse_media'] },
    response: { hits: r() > 0.85 ? 1 : 0, checkedLists: 4 },
    redacted: ['request.name'],
  }),
  corporate_registry: (r) => ({
    record: `Registry BC${1293800 + Math.floor(r() * 99)}`,
    request: { registryNumber: `BC${1293800 + Math.floor(r() * 99)}` },
    response: { status: 'active', owners: [{ name: MASK, pct: 51 }, { name: MASK, pct: 49 }] },
    redacted: ['response.owners[*].name'],
  }),
  get_transactions: (r) => ({
    record: `Card ••${[4471, 2231, 9012, 5508][Math.floor(r() * 4)]}`,
    request: { cardAccount: MASK, from: '2026-09-01' },
    response: { count: 12 + Math.floor(r() * 40), matched: { merchant: 'TRVL*BOOKINGS AMS', amount: 412.18 } },
    redacted: ['request.cardAccount'],
  }),
  issue_provisional_credit: (r) => {
    const amount = Math.round((r() > 0.5 ? 40 + r() * 900 : 1000 + r() * 2400) * 100) / 100;
    return {
      record: `Card ••${[4471, 2231, 9012, 5508][Math.floor(r() * 4)]}`,
      amount,
      request: { cardAccount: MASK, amount, reasonCode: '10.4' },
      response: { creditId: `PC-${31000 + Math.floor(r() * 900)}`, posted: true },
      redacted: ['request.cardAccount'],
    };
  },
  waive_fee: (r) => {
    const amount = r() > 0.5 ? 39 : 15;
    return { record: `Card ••${[6610, 1184, 4471][Math.floor(r() * 3)]}`, amount, request: { cardAccount: MASK, fee: 'late_payment', amount }, response: { waived: true }, redacted: ['request.cardAccount'] };
  },
  search_knowledge: (r) => ({
    request: { query: ['new payee wire hold', 'dispute reason code 10.4', 'jumbo mortgage stress test', 'beneficial owner threshold', 'branch hours King & Bay'][Math.floor(r() * 5)], topK: 6 },
    response: { results: 6, cited: 1 + Math.floor(r() * 3) },
    redacted: [],
  }),
  book_appointment: (r) => ({
    record: `Branch ${['King & Bay', 'Yonge & Eglinton', 'Granville'][Math.floor(r() * 3)]}`,
    request: { branch: 'King & Bay', slot: '2026-10-06T10:30', customerEmail: MASK },
    response: { confirmation: `APT-${5100 + Math.floor(r() * 800)}` },
    redacted: ['request.customerEmail'],
  }),
  transfer_funds: () => ({ record: 'Account CHQ-1182', request: { from: MASK, to: MASK, amount: 500 }, response: {}, redacted: ['request.from', 'request.to'] }),
  update_address: (r) => ({ record: `Customer ${CUSTOMERS[Math.floor(r() * CUSTOMERS.length)]}`, request: { customerId: MASK, address: MASK }, response: { updated: true }, redacted: ['request.customerId', 'request.address'] }),
  get_loan_account: (r) => ({
    record: `Loan ${['7700-31842', '5512-90031', '6620-11407', '7700-28810'][Math.floor(r() * 4)]}`,
    request: { loanId: MASK },
    response: { status: 'current', nextPayment: '2026-11-01', arrearsDays: 0 },
    redacted: ['request.loanId'],
  }),
  apply_payment_deferral: (r) => ({
    record: `Loan ${['7700-31842', '5512-90031'][Math.floor(r() * 2)]}`,
    request: { loanId: MASK, payments: 2, reason: 'job_loss' },
    response: { deferralId: `DF-${880 + Math.floor(r() * 99)}`, resumesOn: '2027-01-01' },
    redacted: ['request.loanId'],
  }),
  send_reply: (r) => ({
    record: `Case reply`,
    request: { to: MASK, subject: 'Re: your request', bodyChars: 400 + Math.floor(r() * 500) },
    response: { messageId: MASK, queued: true },
    redacted: ['request.to', 'response.messageId'],
  }),
};

const ERRORS: Record<string, string> = {
  verify_employment: 'The Work Number did not answer within 8 s.',
  corporate_registry: 'Registry returned 503 Service Unavailable.',
  run_credit_check: 'Equifax rejected the request: consent reference expired.',
  book_appointment: 'Slot no longer available.',
};

/** Writes that pause for a person, unless a gate auto-approves below a threshold. */
const PERSON_APPROVAL = new Set(['place_wire_hold', 'issue_provisional_credit', 'issue_preapproval', 'apply_payment_deferral', 'send_reply', 'update_address', 'waive_fee']);

/** Gate or approval rule each write is evaluated against. Email workflows use their approval rules. */
function policyFor(wid: string, tool: string, amount?: number): { name: string; version: number; rule: string; auto: boolean } | null {
  const gate = (id: string, auto: boolean) => {
    const p = F.POLICIES.find((x) => x.id === id)!;
    return { name: p.name, version: POLICY_VERSION[id] ?? 1, rule: p.condition, auto };
  };
  if (tool === 'place_wire_hold') return gate((amount ?? 0) > 50_000 ? 'gp_1' : 'gp_2', false);
  if (tool === 'issue_preapproval') return gate('gp_3', (amount ?? 0) <= 500_000);
  if (tool === 'issue_provisional_credit' && wid === 'wf_dispute') return gate('gp_7', (amount ?? 0) <= 1000);
  if (tool === 'issue_provisional_credit') return { name: 'Approval rule · Issue provisional credit', version: 3, rule: 'Card Disputes, four eyes, auto below $50', auto: (amount ?? 0) < 50 };
  if (tool === 'waive_fee') return { name: 'Approval rule · Waive a fee', version: 2, rule: 'Card Services Leads, auto below $25', auto: (amount ?? 0) < 25 };
  if (tool === 'apply_payment_deferral') return { name: 'Approval rule · Apply payment deferral', version: 1, rule: 'Lending Servicing Leads, four eyes', auto: false };
  if (tool === 'update_address') return { name: 'Approval rule · Update address', version: 2, rule: 'Account Maintenance', auto: false };
  if (tool === 'send_reply') return { name: 'Approval rule · Send reply to customer', version: 4, rule: 'Queue owner signs off every reply', auto: false };
  if (tool === 'book_appointment') return { name: 'Low-risk writes', version: 2, rule: 'access = write AND tool.requiresReview = false', auto: true };
  return null;
}

const RUNS: Record<string, number> = { wf_wire: 22, wf_mortgage: 14, wf_dispute: 14, wf_kyb: 10, wf_branch_chat: 20, wf_card_inbox: 14, wf_lending_inbox: 10 };
/** Case ids the email workflows opened (see cases/seed.ts: templates 0–9 are card, 10–15 lending). */
const CASES: Record<string, number[]> = {
  wf_card_inbox: [...Array(36).keys()].filter((i) => i % 16 < 10).map((i) => 4100 + i),
  wf_lending_inbox: [...Array(36).keys()].filter((i) => i % 16 >= 10).map((i) => 4100 + i),
};

/** Every call the gateways recorded over the last 7 days, newest first. */
export function seedToolCalls(): ToolCallDetail[] {
  const r = rng(7);
  const out: ToolCallDetail[] = [];
  let seq = 0;
  const openReview = (wid: string) => F.REVIEWS.find((x) => x.workflowId === wid && (x.status === 'pending' || x.status === 'in_review'));

  for (const w of F.WORKFLOWS) {
    const n = RUNS[w.id];
    if (!n) continue;
    const agent = F.AGENTS.find((a) => a.slug === w.agentSlugs[0])!;
    const model = MODEL_ALIAS[agent.model];
    const access = WORKFLOW_ACCESS[w.id];
    const identity = principalOf(w.name);

    for (let k = 0; k < n; k++) {
      const runStart = Math.round(((k + 0.3) / n) ** 1.4 * 7 * 1440 * (0.92 + r() * 0.08)) + 2;
      const runId = `RUN-${w.id.slice(3, 6).toUpperCase()}-${9000 - k}`;
      const cases = CASES[w.id];
      const caseId = cases ? `CASE-${cases[k % cases.length]}` : undefined;
      let offset = 0;
      const push = (c: Omit<ToolCallDetail, 'id' | 'at' | 'workflowId' | 'workflowName' | 'agentSlug' | 'agentName' | 'runId' | 'caseId' | 'identity' | 'requestId'>) => {
        offset += 0.05 + r() * 0.2;
        seq++;
        out.push({
          id: `call_${String(seq).padStart(4, '0')}`,
          at: minsAgo(Math.max(0.5, runStart - offset)),
          workflowId: w.id,
          workflowName: w.name,
          agentSlug: agent.slug,
          agentName: agent.name,
          runId,
          caseId,
          identity,
          requestId: `req_${(seq * 7919).toString(36)}${Math.floor(r() * 1e6).toString(36)}`,
          ...c,
        });
      };
      const modelCall = (purpose: string) => {
        const input = Math.round(1800 + r() * 10_000);
        const output = Math.round(150 + r() * 950);
        push({
          gateway: 'ai',
          target: model.alias,
          system: agent.model,
          operation: 'completion',
          approval: { kind: 'none' },
          status: 'ok',
          latencyMs: Math.round(900 + r() * 3300),
          tokens: { input, output },
          cost: Math.round(((input * model.inPerM + output * model.outPerM) / 1e6) * 10_000) / 10_000,
          request: { alias: model.alias, purpose, messages: `${2 + Math.floor(r() * 5)} messages · ${input.toLocaleString('en-CA')} tokens`, tools: access.tools, temperature: 0.2 },
          response: { stopReason: purpose === 'plan' ? 'tool_use' : 'end_turn', usage: { input, output } },
          redacted: ['request.messages[*].content', 'response.content'],
          policy: { name: 'Model routing', version: 3, rule: `${model.alias} → ${agent.model}, PII redaction on` },
        });
      };

      modelCall('plan');
      for (const tool of access.tools) {
        if (tool === 'search_knowledge' && r() > 0.7) continue;
        const mod = moduleOf(tool);
        const p = PAYLOADS[tool](r, k);
        const toolFixture = F.TOOLS.find((t) => t.name === tool);
        const op: CallOperation = mod.access;
        let approval: CallApproval = { kind: 'none' };
        let status: CallStatus = 'ok';
        let error: string | undefined;
        const pol = op === 'read' ? null : policyFor(w.id, tool, p.amount);
        if (pol) {
          const person = PERSON_APPROVAL.has(tool) && !pol.auto;
          const pending = person && k === 0 && openReview(w.id);
          approval = person
            ? pending
              ? { kind: 'person', reviewId: pending.id }
              : { kind: 'person', tokenId: `apt_${Math.floor(r() * 1e8).toString(36)}`, by: F.REVIEWERS[Math.floor(r() * F.REVIEWERS.length)], at: minsAgo(runStart - offset - 0.1) }
            : { kind: 'policy', tokenId: `apt_${Math.floor(r() * 1e8).toString(36)}`, policyName: pol.name, policyVersion: pol.version };
          if (pending) status = 'awaiting_approval';
        }
        if (status === 'ok' && r() < (toolFixture?.errorRate ?? 0.005) * 4) {
          status = 'error';
          error = ERRORS[tool] ?? `${mod.system} returned 500 Internal Server Error.`;
        }
        push({
          gateway: 'data',
          target: tool,
          system: mod.system,
          operation: op,
          record: tool === 'send_reply' && caseId ? `Case ${caseId}` : p.record,
          approval,
          status,
          latencyMs: Math.round((toolFixture?.p95Ms || 320) * (0.35 + r() * 0.75)),
          request: p.request,
          response: status === 'error' ? { error } : status === 'awaiting_approval' ? {} : p.response,
          redacted: p.redacted,
          error,
          policy: pol ? { name: pol.name, version: pol.version, rule: pol.rule } : { name: 'Access grant', version: 1, rule: `identity holds read on ${moduleLabel(tool)}` },
        });
        if (status === 'awaiting_approval') break;
      }
      if (w.id === 'wf_branch_chat' || w.id === 'wf_mortgage') modelCall('answer');
    }
  }

  // Calls the gateway refused: no grant, or a grant that has expired.
  const denied = (wid: string, tool: string, minutes: number, error: string) => {
    const w = F.WORKFLOWS.find((x) => x.id === wid)!;
    const agent = F.AGENTS.find((a) => a.slug === w.agentSlugs[0])!;
    const mod = moduleOf(tool);
    seq++;
    out.push({
      id: `call_${String(seq).padStart(4, '0')}`,
      at: minsAgo(minutes),
      gateway: 'data',
      workflowId: wid,
      workflowName: w.name,
      agentSlug: agent.slug,
      agentName: agent.name,
      runId: `RUN-${wid.slice(3, 6).toUpperCase()}-${8990}`,
      target: tool,
      system: mod.system,
      operation: mod.access,
      approval: { kind: 'none' },
      status: 'denied',
      latencyMs: 4,
      identity: principalOf(w.name),
      requestId: `req_${(seq * 7919).toString(36)}den`,
      request: { [tool === 'transfer_funds' ? 'from' : 'cardAccount']: MASK },
      response: { error },
      redacted: [tool === 'transfer_funds' ? 'request.from' : 'request.cardAccount'],
      policy: { name: 'Access grant', version: 1, rule: `identity holds ${mod.access.replace('_', ' ')} on ${moduleLabel(tool)}` },
      error,
    });
  };
  denied('wf_branch_chat', 'get_transactions', 95, 'Grant expired: Card Platform · get_transactions expired 2 days ago.');
  denied('wf_branch_chat', 'get_transactions', 1420, 'Grant expired: Card Platform · get_transactions expired 2 days ago.');
  denied('wf_mortgage', 'transfer_funds', 3100, 'No grant for Core Banking · transfer_funds on this workflow identity.');

  return out.sort((a, b) => b.at.localeCompare(a.at));
}
