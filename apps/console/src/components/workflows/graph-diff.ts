import type { WorkflowGraph } from '@/lib/types/domain';

type Node = WorkflowGraph['nodes'][number];

/** Differences between the published graph and the draft, by step, so a publisher sees what they ship. */
export function diffGraphs(before: WorkflowGraph, after: { nodes: Node[]; edges: WorkflowGraph['edges']; emailConfig?: WorkflowGraph['emailConfig'] }) {
  const byId = new Map(before.nodes.map((n) => [n.id, n]));
  const added = after.nodes.filter((n) => !byId.has(n.id));
  const removed = before.nodes.filter((n) => !after.nodes.some((x) => x.id === n.id));
  const changed = after.nodes.filter((n) => {
    const b = byId.get(n.id);
    if (!b) return false;
    const pick = (x: Node) => JSON.stringify({ ...x.data, status: undefined });
    return pick(b) !== pick(n);
  });
  const edgeKey = (e: WorkflowGraph['edges'][number]) => `${e.source}>${e.sourceHandle ?? ''}>${e.target}`;
  const beforeEdges = new Set(before.edges.map(edgeKey));
  const afterEdges = new Set(after.edges.map(edgeKey));
  const rewired = [...afterEdges].filter((k) => !beforeEdges.has(k)).length + [...beforeEdges].filter((k) => !afterEdges.has(k)).length;
  // Email intake settings are compared per section, since they are edited as forms rather than nodes.
  const b = before.emailConfig;
  const a = after.emailConfig;
  const config: string[] = [];
  if (b && a) {
    const same = (x: unknown, y: unknown) => JSON.stringify(x) === JSON.stringify(y);
    if (!same(b.intents, a.intents)) config.push('Changed intents');
    if (!same(b.routes, a.routes) || b.fallbackQueue !== a.fallbackQueue || b.confidenceThreshold !== a.confidenceThreshold) config.push('Changed routing and SLAs');
    if (!same(b.approvals, a.approvals)) config.push('Changed approval rules');
  }
  return { added, removed, changed, rewired, config };
}
