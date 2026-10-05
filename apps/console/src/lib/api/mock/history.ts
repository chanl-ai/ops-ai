import type { AgentTestTurn, RunStatus, RunStep, Version, WorkflowGraph, WorkflowRun } from '@/lib/types/domain';

/** Deterministic generators for mock history (runs, versions, performance), so reloads look the same. */

function seeded(seed: string) {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    return ((h >>> 0) % 10_000) / 10_000;
  };
}

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const PUBLISHERS = ['James Richardson', 'Maya Okafor', 'Anika Singh', 'Daniel Brooks'];
const WORKFLOW_NOTES = [
  ['Raised the review threshold from $25,000 to $50,000', 'Added callback step before release'],
  ['Added the high-risk jurisdiction gate'],
  ['Switched scoring to claude-sonnet-5'],
  ['Shortened analyst SLA from 1 h to 30 min'],
  ['Added SLA-lapsed path to the hold step'],
  ['Initial version'],
];
const AGENT_NOTES = [
  ['Tightened release rule: callback required before any release'],
  ['Granted search_knowledge', 'Attached Compliance collection'],
  ['Instructions: cite the playbook section for each decision'],
  ['Model changed to claude-sonnet-5'],
  ['Owner moved to Fraud Strategy'],
  ['Initial version'],
];

export function versionsFor(key: string, current: number, kind: 'workflow' | 'agent'): Version[] {
  const rnd = seeded(key);
  const notes = kind === 'workflow' ? WORKFLOW_NOTES : AGENT_NOTES;
  const out: Version[] = [];
  let minutes = 60 * (6 + Math.round(rnd() * 40));
  for (let v = current; v >= Math.max(1, current - 5); v--) {
    const changes = v === 1 ? ['Initial version'] : notes[(current - v) % (notes.length - 1)];
    out.push({ version: v, publishedAt: ago(minutes), publishedBy: PUBLISHERS[Math.floor(rnd() * PUBLISHERS.length)], note: changes[0], changes, current: v === current });
    minutes += 60 * (24 + Math.round(rnd() * 120));
  }
  return out;
}

const SUBJECTS = ['Hartwell Dental Corp', 'Lin & Moreau LLP', 'Sarah Chen', 'Daniel Okoye', 'Northgate Logistics', 'Priya Natarajan', 'Marcus Webb', 'Brennan Orthodontics', 'Tomás Alvarez', 'Grace Kim', 'Coastal Imports', 'Elena Vasquez', 'Brightline Studio', 'Aurelia Holdings', 'Owen Fraser', 'Leila Haddad'];

const KIND: Record<string, RunStep['kind']> = { trigger: 'trigger', review: 'review', end: 'end', router: 'agent' };

/** Walks the main path of a graph (first edge out of each node, stopping at a review gate when the run is waiting). */
function pathOf(graph: WorkflowGraph, stopAtReview: boolean) {
  const start = graph.nodes.find((n) => n.type === 'trigger');
  const path: WorkflowGraph['nodes'] = [];
  let cur = start;
  while (cur && !path.includes(cur)) {
    path.push(cur);
    if (cur.type === 'review' && stopAtReview) break;
    const id = cur.id;
    const next = graph.edges.find((e) => e.source === id && (e.sourceHandle == null || ['mid', 'Gate', 'approved'].includes(e.sourceHandle)));
    cur = next ? graph.nodes.find((n) => n.id === next.target) : undefined;
  }
  return path;
}

export function runsFor(workflowId: string, graph: WorkflowGraph | undefined, version: number, openReviewIds: string[], count = 46): WorkflowRun[] {
  if (!graph?.nodes.length) return [];
  const rnd = seeded(workflowId);
  const runs: WorkflowRun[] = [];
  let minutes = 3;
  for (let i = 0; i < count; i++) {
    const roll = rnd();
    const status: RunStatus = i < openReviewIds.length ? 'waiting_review' : i === 0 ? 'running' : roll < 0.07 ? 'failed' : 'completed';
    const path = pathOf(graph, status === 'waiting_review');
    const failAt = status === 'failed' ? Math.max(1, Math.floor(rnd() * (path.length - 1))) : -1;
    const steps: RunStep[] = path.map((n, idx) => {
      const kind = KIND[n.type] ?? (n.data.category === 'tool' ? 'tool' : n.data.category === 'response' || n.data.category === 'control' ? 'action' : 'agent');
      const waiting = status === 'waiting_review' && n.type === 'review';
      const failed = idx === failAt;
      const skipped = failAt >= 0 && idx > failAt;
      return {
        nodeId: n.id,
        label: n.data.label,
        kind,
        status: failed ? 'failed' : skipped ? 'skipped' : waiting || (status === 'running' && idx === path.length - 1) ? 'waiting' : 'done',
        durationMs: skipped ? 0 : Math.round(80 + rnd() * (kind === 'agent' ? 2400 : 600)),
        detail: failed ? 'Upstream returned 504 after 3 retries' : waiting ? `Paused for ${n.data.reviewers ?? 'reviewer'}` : n.data.description || undefined,
      };
    });
    runs.push({
      id: `RUN-${workflowId.slice(3, 6).toUpperCase()}-${String(9000 - i).padStart(4, '0')}`,
      workflowId,
      version: i < 30 ? version : Math.max(1, version - 1),
      subject: SUBJECTS[Math.floor(rnd() * SUBJECTS.length)],
      status,
      startedAt: ago(minutes),
      durationMs: steps.reduce((s, x) => s + x.durationMs, 0),
      reviewId: status === 'waiting_review' ? openReviewIds[i] : undefined,
      error: status === 'failed' ? 'A tool call failed; the run stopped before acting.' : undefined,
      steps,
    });
    minutes += Math.round(4 + rnd() * 40);
  }
  return runs;
}


/** Canned test reply that exercises the agent's own tools and gates, so the test panel shows a realistic turn. */
export function testTurnFor(agent: { slug: string; name: string }, message: string, tools: string[]): AgentTestTurn {
  const moneyish = /wire|transfer|refund|credit|release|hold|\$\d/i.test(message);
  const tool = tools.find((t) => t !== 'search_knowledge') ?? tools[0];
  return {
    reply: moneyish
      ? `I checked the account and the request matches the conditions that need a person. I've prepared the action and sent it for review rather than acting on it.`
      : `Here is what I found. I can take the next step once you confirm the details.`,
    toolCalls: [
      ...(tools.includes('search_knowledge') ? [{ name: 'search_knowledge', input: JSON.stringify({ query: message.slice(0, 60) }), output: '3 passages · top score 0.91' }] : []),
      ...(tool && tool !== 'search_knowledge' ? [{ name: tool, input: '{ "accountId": "8821-004417" }', output: '{ "status": "ok" }' }] : []),
    ],
    citations: tools.includes('search_knowledge') ? [{ source: 'Wire Fraud Playbook', section: '§4.2 New-payee wires' }] : [],
    wouldPause: moneyish ? { gate: 'High-value new payee', reviewers: 'Fraud Analysts L2' } : undefined,
    tookMs: 900 + message.length * 12,
  };
}
