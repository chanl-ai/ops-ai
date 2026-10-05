import type { EmailWorkflowConfig } from '@/lib/types/cases';
import type { WorkflowGraph, WorkflowNodeData } from '@/lib/types/domain';

import { EMAIL_CONFIGS } from './cases/configs';

type N = WorkflowGraph['nodes'][number];
type Edge = WorkflowGraph['edges'][number];
type StepData = WorkflowNodeData;

const X = 270;
const node = (id: string, type: string, col: number, y: number, data: StepData): N => ({ id, type, position: { x: col * X, y }, data });
const edge = (source: string, target: string, opts: Partial<Edge> = {}): Edge => ({
  id: `${source}-${opts.sourceHandle ?? 'out'}-${target}`,
  source,
  target,
  type: 'smoothstep',
  ...opts,
});
const approved = (s: string, t: string) => edge(s, t, { sourceHandle: 'approved', label: 'Approved', style: { stroke: '#10b981' } });
const rejected = (s: string, t: string) => edge(s, t, { sourceHandle: 'rejected', label: 'Rejected', style: { stroke: '#ef4444' } });
const timeout = (s: string, t: string) => edge(s, t, { sourceHandle: 'timeout', label: 'SLA lapsed', style: { strokeDasharray: '4 4' } });

const GRAPHS: Record<string, { nodes: N[]; edges: Edge[] }> = {
  wf_wire: {
    nodes: [
      node('t', 'trigger', 0, 200, { label: 'Wire initiated', description: 'Payments Hub · ≥ $10,000', icon: 'globe', category: 'trigger' }),
      node('hist', 'step', 1, 200, { label: 'Load wire history', description: 'get_wire_history', icon: 'wrench', category: 'tool' }),
      node('dev', 'step', 2, 200, { label: 'Device & session', description: 'device_fingerprint', icon: 'shield', category: 'guard' }),
      node('score', 'step', 3, 200, { label: 'Score fraud risk', description: 'Wire Fraud Playbook', icon: 'brain', category: 'ai', badge: 'agent · fraud-sentinel', agentSlug: 'fraud-sentinel' }),
      node('route', 'branch', 4, 170, { label: 'Route by risk', description: 'Fraud risk of the wire', icon: 'branch', category: 'ai', kind: 'classify', branches: ['Low', 'Gate', 'Block'] }),
      node('release', 'step', 5, 20, { label: 'Release wire', description: 'place_wire_hold · release', icon: 'send', category: 'response' }),
      node('review', 'review', 5, 200, { label: 'Fraud analyst review', description: '', icon: 'user', category: 'human', reviewers: 'Fraud Analysts L2', sla: '30 min', condition: 'amount > 50,000 AND payee.age < 72h', fourEyes: true }),
      node('block', 'step', 5, 430, { label: 'Block & page on-call', description: 'Sanctions or mule match', icon: 'alert', category: 'control' }),
      node('hold', 'step', 6, 160, { label: 'Place 24h hold', description: 'place_wire_hold', icon: 'wrench', category: 'tool' }),
      node('call', 'step', 7, 160, { label: 'Call account holder', description: 'Number on file only', icon: 'phone', category: 'response' }),
      node('done', 'end', 8, 175, { label: 'Done', description: '', icon: 'check', category: 'control' }),
      node('stopped', 'end', 6, 445, { label: 'Stopped', description: '', icon: 'x', category: 'control' }),
    ],
    edges: [
      edge('t', 'hist'), edge('hist', 'dev'), edge('dev', 'score'), edge('score', 'route'),
      edge('route', 'release', { sourceHandle: 'Low' }),
      edge('route', 'review', { sourceHandle: 'Gate' }),
      edge('route', 'block', { sourceHandle: 'Block' }),
      approved('review', 'hold'), rejected('review', 'release'), timeout('review', 'hold'),
      edge('hold', 'call'), edge('call', 'done'), edge('release', 'done'), edge('block', 'stopped'),
    ],
  },
  wf_mortgage: {
    nodes: [
      node('t', 'trigger', 0, 200, { label: 'Application submitted', description: 'Web · branch · broker', icon: 'file', category: 'trigger' }),
      node('intake', 'step', 1, 200, { label: 'Collect & pre-screen', description: 'Missing docs, eligibility', icon: 'sparkles', category: 'ai', badge: 'agent · mortgage-intake', agentSlug: 'mortgage-intake' }),
      node('credit', 'step', 2, 200, { label: 'Credit check', description: 'run_credit_check', icon: 'wrench', category: 'tool' }),
      node('emp', 'step', 3, 200, { label: 'Verify employment', description: 'verify_employment', icon: 'wrench', category: 'tool' }),
      node('kb', 'step', 4, 200, { label: 'Underwriting rules', description: 'Underwriting Guide v4.2', icon: 'book', category: 'data' }),
      node('draft', 'step', 5, 200, { label: 'Draft decision', description: 'Rate, term, conditions', icon: 'brain', category: 'ai', badge: 'agent · mortgage-intake', agentSlug: 'mortgage-intake' }),
      node('review', 'review', 6, 190, { label: 'Underwriter review', description: '', icon: 'user', category: 'human', reviewers: 'Underwriters', sla: '4 h', condition: 'loan.amount > 500,000 OR appeal', fourEyes: false }),
      node('issue', 'step', 7, 100, { label: 'Issue pre-approval', description: 'issue_preapproval', icon: 'wrench', category: 'tool' }),
      node('offer', 'step', 8, 100, { label: 'Send offer', description: 'Email + portal', icon: 'send', category: 'response' }),
      node('decline', 'step', 7, 340, { label: 'Send decline', description: 'With adverse-action reasons', icon: 'message', category: 'response' }),
      node('done', 'end', 9, 115, { label: 'Pre-approved', description: '', icon: 'check', category: 'control' }),
      node('declined', 'end', 8, 355, { label: 'Declined', description: '', icon: 'x', category: 'control' }),
    ],
    edges: [
      edge('t', 'intake'), edge('intake', 'credit'), edge('credit', 'emp'), edge('emp', 'kb'), edge('kb', 'draft'), edge('draft', 'review'),
      approved('review', 'issue'), rejected('review', 'decline'), timeout('review', 'decline'),
      edge('issue', 'offer'), edge('offer', 'done'), edge('decline', 'declined'),
    ],
  },
  wf_dispute: {
    nodes: [
      node('t', 'trigger', 0, 200, { label: 'Dispute filed', description: 'App · phone · chat', icon: 'message', category: 'trigger' }),
      node('txn', 'step', 1, 200, { label: 'Pull transactions', description: 'get_transactions', icon: 'wrench', category: 'tool' }),
      node('classify', 'step', 2, 200, { label: 'Classify reason code', description: 'Dispute Rights Guide', icon: 'brain', category: 'ai', badge: 'agent · dispute-resolver', agentSlug: 'dispute-resolver' }),
      node('review', 'review', 3, 190, { label: 'Disputes review', description: '', icon: 'user', category: 'human', reviewers: 'Card Disputes', sla: '8 h', condition: 'credit.amount > 1,000', fourEyes: false }),
      node('credit', 'step', 4, 100, { label: 'Provisional credit', description: 'issue_provisional_credit', icon: 'wrench', category: 'tool' }),
      node('notify', 'step', 5, 200, { label: 'Notify cardholder', description: 'Outcome + next steps', icon: 'send', category: 'response' }),
      node('done', 'end', 6, 215, { label: 'Done', description: '', icon: 'check', category: 'control' }),
    ],
    edges: [
      edge('t', 'txn'), edge('txn', 'classify'), edge('classify', 'review'),
      approved('review', 'credit'), rejected('review', 'notify'), timeout('review', 'credit'),
      edge('credit', 'notify'), edge('notify', 'done'),
    ],
  },
  wf_kyb: {
    nodes: [
      node('t', 'trigger', 0, 200, { label: 'Business application', description: 'Online account opening', icon: 'file', category: 'trigger' }),
      node('reg', 'step', 1, 200, { label: 'Corporate registry', description: 'corporate_registry', icon: 'wrench', category: 'tool' }),
      node('id', 'step', 2, 200, { label: 'Verify owners', description: 'id_verify', icon: 'shield', category: 'guard' }),
      node('screen', 'step', 3, 200, { label: 'Watchlist screening', description: 'screen_watchlists', icon: 'wrench', category: 'tool' }),
      node('assess', 'step', 4, 200, { label: 'Assess file', description: 'AML & KYC Procedures', icon: 'brain', category: 'ai', badge: 'agent · kyb-verifier', agentSlug: 'kyb-verifier' }),
      node('review', 'review', 5, 190, { label: 'KYC operations', description: '', icon: 'user', category: 'human', reviewers: 'Enhanced Due Diligence', sla: '2 h', condition: 'screening.pep OR nameMatch < 0.90', fourEyes: true }),
      node('open', 'step', 6, 100, { label: 'Open account', description: 'Core Banking', icon: 'check', category: 'control' }),
      node('docs', 'step', 6, 330, { label: 'Request documents', description: 'request_documents', icon: 'message', category: 'response' }),
      node('done', 'end', 7, 115, { label: 'Opened', description: '', icon: 'check', category: 'control' }),
    ],
    edges: [
      edge('t', 'reg'), edge('reg', 'id'), edge('id', 'screen'), edge('screen', 'assess'), edge('assess', 'review'),
      approved('review', 'open'), rejected('review', 'docs'), timeout('review', 'docs'), edge('open', 'done'),
    ],
  },
  wf_advisor: {
    nodes: [
      node('t', 'trigger', 0, 200, { label: 'Quarterly schedule', description: 'First business day', icon: 'clock', category: 'trigger' }),
      node('load', 'step', 1, 200, { label: 'Load portfolio', description: 'Wealth data feed', icon: 'database', category: 'data' }),
      node('draft', 'step', 2, 200, { label: 'Draft review notes', description: 'Model portfolio policy', icon: 'sparkles', category: 'ai', badge: 'agent · advisor-copilot', agentSlug: 'advisor-copilot' }),
      node('review', 'review', 3, 190, { label: 'Advisor sign-off', description: '', icon: 'user', category: 'human', reviewers: 'Assigned advisor', sla: '3 days', condition: 'always', fourEyes: false }),
      node('send', 'step', 4, 200, { label: 'Share with client', description: 'Secure message', icon: 'send', category: 'response' }),
    ],
    edges: [edge('t', 'load'), edge('load', 'draft'), edge('draft', 'review'), approved('review', 'send')],
  },
};

/** Email intake workflows share one shape; their behaviour lives in emailConfig, which the canvas renders read-only. */
function emailGraph(mailbox: string, agent: string, config: EmailWorkflowConfig): { nodes: N[]; edges: Edge[]; emailConfig: EmailWorkflowConfig } {
  return {
    emailConfig: config,
    nodes: [
      node('t', 'trigger', 0, 200, { label: 'Email received', description: mailbox, icon: 'mail', category: 'trigger', kind: 'email' }),
      node('read', 'step', 1, 200, { label: 'Read email + attachments', description: 'Text, PDFs and images', icon: 'file', category: 'data' }),
      node('classify', 'branch', 2, 170, { label: 'Understand intent', description: `${config.intents.length} intents`, icon: 'branch', category: 'ai', kind: 'classify', branches: ['Matched', 'Unsure'] }),
      node('case', 'step', 3, 60, { label: 'Open case', description: 'Queue, priority, SLA from routing', icon: 'database', category: 'control' }),
      node('fallback', 'step', 3, 340, { label: 'Fallback queue', description: config.fallbackQueue, icon: 'database', category: 'control' }),
      node('draft', 'step', 4, 60, { label: 'Draft actions', description: 'Tool calls and reply', icon: 'sparkles', category: 'ai', kind: 'agent', badge: `agent · ${agent}`, agentSlug: agent }),
      node('review', 'review', 5, 50, { label: 'Approve each action', description: '', icon: 'user', category: 'human', reviewers: 'Per approval rules', sla: 'Per routing', condition: 'per action', fourEyes: true }),
      node('act', 'step', 6, 60, { label: 'Run approved actions', description: 'Tool gateway', icon: 'send', category: 'response' }),
    ],
    edges: [edge('t', 'read'), edge('read', 'classify'), edge('classify', 'case', { sourceHandle: 'Matched' }), edge('classify', 'fallback', { sourceHandle: 'Unsure' }), edge('case', 'draft'), edge('draft', 'review'), approved('review', 'act')],
  };
}

export const SEED_GRAPHS = {
  ...GRAPHS,
  wf_card_inbox: emailGraph('cardservices@northfieldbank.com', 'dispute-resolver', EMAIL_CONFIGS.wf_card_inbox),
  wf_lending_inbox: emailGraph('lendingservicing@northfieldbank.com', 'mortgage-intake', EMAIL_CONFIGS.wf_lending_inbox),
  wf_branch_chat: templateGraph('chat', 'Chat message', { slug: 'branch-concierge', name: 'Branch Concierge', version: 12 }),
};

/** Starting graph for a workflow created from a template in the New workflow dialog. */
export function templateGraph(
  template: 'blank' | 'approval' | 'triage' | 'chat',
  trigger: string,
  agent?: { slug: string; name: string; version: number },
): { nodes: N[]; edges: Edge[] } {
  if (template === 'chat')
    return {
      nodes: [
        node('t', 'trigger', 0, 200, { label: 'Chat message', description: 'Widget or chat API', icon: 'message', category: 'trigger', kind: 'chat' }),
        node('agent', 'step', 1, 200, { label: agent?.name ?? 'Agent', description: 'Answers the customer', icon: 'bot', category: 'ai', kind: 'agent', agentSlug: agent?.slug, agentVersion: agent?.version, badge: agent ? `agent · ${agent.slug} · v${agent.version}` : undefined }),
        node('reply', 'step', 2, 200, { label: 'Reply', description: 'On the same channel', icon: 'send', category: 'output', kind: 'reply' }),
      ],
      edges: [edge('t', 'agent'), edge('agent', 'reply')],
    };
  const t = node('t', 'trigger', 0, 200, { label: trigger, description: 'Trigger', icon: 'zap', category: 'trigger' });
  if (template === 'blank') return { nodes: [t], edges: [] };
  if (template === 'triage')
    return {
      nodes: [
        t,
        node('route', 'branch', 1, 170, { label: 'Route by intent', description: '', icon: 'branch', category: 'ai', kind: 'classify', branches: ['Question', 'Request', 'Complaint'] }),
        node('a', 'step', 2, 60, { label: 'Answer', description: '', icon: 'bot', category: 'ai', kind: 'agent' }),
        node('b', 'step', 2, 200, { label: 'Handle request', description: '', icon: 'bot', category: 'ai', kind: 'agent' }),
        node('c', 'step', 2, 340, { label: 'Hand off', description: '', icon: 'headset', category: 'human', kind: 'handoff' }),
      ],
      edges: [edge('t', 'route'), edge('route', 'a', { sourceHandle: 'Question' }), edge('route', 'b', { sourceHandle: 'Request' }), edge('route', 'c', { sourceHandle: 'Complaint' })],
    };
  return {
    nodes: [
      t,
      node('agent', 'step', 1, 200, { label: 'Agent', description: '', icon: 'bot', category: 'ai', kind: 'agent' }),
      node('review', 'review', 2, 190, { label: 'Approval', description: '', icon: 'user', category: 'human', kind: 'approval', reviewers: 'Unassigned group', sla: '1 h', condition: 'always', fourEyes: false }),
      node('act', 'step', 3, 100, { label: 'Take action', description: '', icon: 'wrench', category: 'tool', kind: 'tool' }),
    ],
    edges: [edge('t', 'agent'), edge('agent', 'review'), approved('review', 'act')],
  };
}

export const countSteps = (g: { nodes: N[] }) => g.nodes.filter((n) => n.type !== 'trigger' && n.type !== 'end').length;
export const countGates = (g: { nodes: N[] }) => g.nodes.filter((n) => n.type === 'review').length;
