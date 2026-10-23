import type { NodeBox } from './node-size.ts';

export interface LayoutEdge {
  id: string;
  source: string;
  sourcePort?: string;
  target: string;
  targetPort?: string;
}

/** Steps and lines in definition order; the layout keeps that order for ties, so a definition always lays out alike. */
export interface LayoutGraph {
  nodes: NodeBox[];
  edges: LayoutEdge[];
}

export interface Layout {
  positions: Record<string, { x: number; y: number }>;
  width: number;
  height: number;
}

/** The gap between columns, and between steps in one column. A run badge (about 29 px) fits in the column gap. */
export const COLUMN_GAP = 96;
export const ROW_GAP = 40;

// ELK's layered algorithm, left to right. Ports sit at fixed heights so lines leave a step in the order of its ports;
// orthogonal routing makes ELK keep lanes free for lines that skip columns, which the canvas's router then uses. Steps
// with no incoming line join the first layer instead of being packed as separate components.
const ROOT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.separateConnectedComponents': 'false',
  'elk.layered.spacing.nodeNodeBetweenLayers': String(COLUMN_GAP),
  'elk.spacing.nodeNode': String(ROW_GAP),
  'elk.spacing.edgeNode': '20',
  'elk.spacing.edgeEdge': '12',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  // A retry loop (a refused write back to its review) is drawn as the line going back, never the review moved after
  // its own write: the line that runs against definition order is the one reversed.
  'elk.layered.cycleBreaking.strategy': 'MODEL_ORDER',
  'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
  'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
};

const portId = (node: string, side: 'in' | 'out', name: string) => `${node}\u0000${side}\u0000${name}`;

interface ElkLike {
  layout(graph: unknown): Promise<{ children?: { id: string; x?: number; y?: number }[]; width?: number; height?: number }>;
}

let elk: Promise<ElkLike> | null = null;

/** ELK is about 1.5 MB, so it is fetched the first time something needs placing and never on a page that does not. */
function loadElk(): Promise<ElkLike> {
  elk ??= import('elkjs/lib/elk.bundled.js').then((m) => {
    const Elk = (m as unknown as { default: new () => ElkLike }).default;
    return new Elk();
  });
  return elk;
}

/** Positions for every step, rounded to whole pixels, with the first step in definition order at {0, 0}. */
export async function layoutGraph(graph: LayoutGraph): Promise<Layout> {
  if (graph.nodes.length === 0) return { positions: {}, width: 0, height: 0 };
  const ports = new Map(graph.nodes.map((n) => [n.id, { ins: new Set(n.inPorts.map((p) => p.name)), outs: new Set(n.outPorts.map((p) => p.name)) }]));
  const known = new Set(graph.nodes.map((n) => n.id));
  const children = graph.nodes.map((n) => ({
    id: n.id,
    width: n.width,
    height: n.height,
    layoutOptions: { 'elk.portConstraints': 'FIXED_POS' },
    ports: [
      ...n.inPorts.map((p) => ({ id: portId(n.id, 'in', p.name), x: 0, y: p.y, width: 0, height: 0, layoutOptions: { 'elk.port.side': 'WEST' } })),
      ...n.outPorts.map((p) => ({ id: portId(n.id, 'out', p.name), x: n.width, y: p.y, width: 0, height: 0, layoutOptions: { 'elk.port.side': 'EAST' } })),
    ],
  }));
  // A line to a port the step's type does not draw (an unknown type, a removed option) still ties the two steps.
  const edges = graph.edges
    .filter((e) => known.has(e.source) && known.has(e.target) && e.source !== e.target)
    .map((e) => ({
      id: e.id,
      sources: [e.sourcePort && ports.get(e.source)?.outs.has(e.sourcePort) ? portId(e.source, 'out', e.sourcePort) : e.source],
      targets: [e.targetPort && ports.get(e.target)?.ins.has(e.targetPort) ? portId(e.target, 'in', e.targetPort) : e.target],
    }));
  const laid = await (await loadElk()).layout({ id: 'root', layoutOptions: ROOT_OPTIONS, children, edges });
  return normalised(graph, Object.fromEntries((laid.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }])));
}

/** Every step in its own column in definition order: what the canvas draws when ELK cannot load or fails. */
export function rowFallback(graph: LayoutGraph): Layout {
  let x = 0;
  const raw: Record<string, { x: number; y: number }> = {};
  for (const n of graph.nodes) {
    raw[n.id] = { x, y: 0 };
    x += n.width + COLUMN_GAP;
  }
  return normalised(graph, raw);
}

function normalised(graph: LayoutGraph, raw: Record<string, { x: number; y: number }>): Layout {
  const first = raw[graph.nodes[0].id] ?? { x: 0, y: 0 };
  const positions: Record<string, { x: number; y: number }> = {};
  let right = 0;
  let bottom = 0;
  for (const n of graph.nodes) {
    const p = raw[n.id] ?? first;
    // `+ 0` turns -0 into 0, so a stored position compares equal to the one a re-layout gives.
    const at = { x: Math.round(p.x - first.x) + 0, y: Math.round(p.y - first.y) + 0 };
    positions[n.id] = at;
    right = Math.max(right, at.x + n.width);
    bottom = Math.max(bottom, at.y + n.height);
  }
  const left = Math.min(...Object.values(positions).map((p) => p.x));
  const top = Math.min(...Object.values(positions).map((p) => p.y));
  return { positions, width: right - left, height: bottom - top };
}
