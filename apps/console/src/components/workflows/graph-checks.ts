import type { WorkflowGraph } from '@/lib/types/domain';

import { resolveKind, type StepData } from './node-types';

type G = Pick<WorkflowGraph, 'nodes' | 'edges'>;

export interface GraphIssue {
  nodeId?: string;
  severity: 'error' | 'warning';
  message: string;
}

/**
 * Structural checks a workflow must pass to run sensibly: every step wired in, every agent and tool
 * chosen, every gate assigned, and no money-moving step reachable without a review gate.
 */
export function graphIssues(g: G, ctx: { agentSlugs: string[]; toolNames: string[]; moneyTools: string[] }): GraphIssue[] {
  const issues: GraphIssue[] = [];
  const trigger = g.nodes.find((n) => n.type === 'trigger' && n.data.kind !== 'error');
  if (!trigger) issues.push({ severity: 'error', message: 'Add a trigger so the workflow can start.' });

  for (const n of g.nodes) {
    const name = n.data.label || 'Unnamed step';
    const hasIn = g.edges.some((e) => e.target === n.id);
    const hasOut = g.edges.some((e) => e.source === n.id);
    if (n.type !== 'trigger' && !hasIn) issues.push({ nodeId: n.id, severity: 'error', message: `${name} is not connected to anything before it.` });
    if (n.type !== 'end' && n.type !== 'review' && n.type !== 'branch' && !hasOut && n.type !== 'trigger') {
      // A step with no outgoing edge simply ends the run; only flag it when it is not obviously terminal.
      if (!['response', 'control', 'output'].includes(n.data.category)) issues.push({ nodeId: n.id, severity: 'warning', message: `${name} has no next step; runs will stop there.` });
    }
    if (n.type === 'trigger' && !hasOut && g.nodes.length > 1 && n.data.kind !== 'error') issues.push({ nodeId: n.id, severity: 'error', message: 'The trigger is not connected to a first step.' });
    const kind = resolveKind({ type: n.type, data: n.data as StepData });
    if (kind?.id === 'agent' && !(n.data.agentSlug && ctx.agentSlugs.includes(n.data.agentSlug as string)))
      issues.push({ nodeId: n.id, severity: 'error', message: `Choose an agent for ${name}.` });
    else if (kind?.id === 'tool' && !ctx.toolNames.includes(n.data.description))
      issues.push({ nodeId: n.id, severity: 'error', message: `Choose a tool for ${name}.` });
    else
      for (const f of kind?.fields ?? [])
        if (f.required && !String(n.data[f.key] ?? '').trim()) issues.push({ nodeId: n.id, severity: 'error', message: `Fill in “${f.label}” on ${name}.` });
    if (n.type === 'branch')
      for (const b of (n.data.branches as string[] | undefined) ?? [])
        if (!g.edges.some((e) => e.source === n.id && e.sourceHandle === b)) issues.push({ nodeId: n.id, severity: 'warning', message: `${name}: the ${b} path goes nowhere.` });
    if (n.type === 'review' && (!n.data.reviewers || n.data.reviewers === 'Unassigned group')) issues.push({ nodeId: n.id, severity: 'error', message: `Choose reviewers for ${name}.` });
    if (n.type === 'review' && !g.edges.some((e) => e.source === n.id && e.sourceHandle === 'approved'))
      issues.push({ nodeId: n.id, severity: 'warning', message: `${name} has no Approved path; approved runs will stop.` });
  }

  if (trigger && unguardedMoney(g, trigger.id, ctx.moneyTools))
    issues.push({ severity: 'warning', message: 'A step that moves money can be reached without a review gate.' });
  return issues;
}

function unguardedMoney(g: G, start: string, moneyTools: string[]) {
  const seen = new Set<string>();
  const stack = [start];
  while (stack.length) {
    const id = stack.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    const n = g.nodes.find((x) => x.id === id);
    if (!n || n.type === 'review') continue;
    if (moneyTools.includes(n.data.description)) return true;
    g.edges.filter((e) => e.source === id).forEach((e) => stack.push(e.target));
  }
  return false;
}
