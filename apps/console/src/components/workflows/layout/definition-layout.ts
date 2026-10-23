import type { EngineDefinition, EngineNode, EngineNodeType } from '@/lib/types/engine';

import { connectionId, indexTypes, typeKey } from '../definition-editor/graph.ts';
import { COLUMN_GAP, type Layout, type LayoutGraph, layoutGraph, ROW_GAP, rowFallback } from './layout.ts';
import { definitionNodeSize } from './node-size.ts';

type Point = { x: number; y: number };

/** A definition as the layout sees it: each step's box and ports from its type, each connection by port. */
export function definitionGraph(def: EngineDefinition, types: EngineNodeType[]): LayoutGraph {
  const index = indexTypes(types);
  return {
    nodes: def.nodes.map((n) => definitionNodeSize(n, index.get(typeKey(n.type, n.typeVersion)), def.nodes)),
    edges: def.connections.map((c) => ({ id: connectionId(c), source: c.from.node, sourcePort: c.from.port, target: c.to.node, targetPort: c.to.port })),
  };
}

/** Positions for every step of the definition, the first step at {0, 0}. Falls back to one step per column. */
export async function layoutDefinition(def: EngineDefinition, types: EngineNodeType[]): Promise<Layout> {
  const graph = definitionGraph(def, types);
  try {
    return await layoutGraph(graph);
  } catch (e) {
    console.error('Workflow layout failed; placing steps in a row', e);
    return rowFallback(graph);
  }
}

/** The definition with every step at the layout's position. Tidy up and the seed bake both write positions through it. */
export function applyLayout(def: EngineDefinition, layout: Layout): EngineDefinition {
  return { ...def, nodes: def.nodes.map((n) => (layout.positions[n.id] ? { ...n, position: layout.positions[n.id] } : n)) };
}

const same = (a: Point | undefined, b: Point | undefined) => !!a && !!b && a.x === b.x && a.y === b.y;
const ORIGIN = { x: 0, y: 0 };

/**
 * Whether the definition was never placed: more than one step, all at one position. The engine stores a missing
 * position as {0, 0}, so a definition created without positions arrives with every step there.
 */
export function neverPlaced(def: EngineDefinition): boolean {
  if (def.nodes.length < 2) return false;
  const first = def.nodes[0].position ?? ORIGIN;
  return def.nodes.every((n) => same(n.position ?? ORIGIN, first));
}

/**
 * The steps a partly placed definition does not place. The first step keeps its position whatever it is. A later step
 * is unplaced when it has no position, sits at {0, 0} (where the engine puts a step created without one; every layout
 * this module writes keeps the origin for the first step), or sits exactly on an earlier step.
 */
export function unplacedSteps(def: EngineDefinition): Set<string> {
  const out = new Set<string>();
  const seen: Point[] = [];
  def.nodes.forEach((n, i) => {
    const p = n.position;
    if (i > 0 && (!p || same(p, ORIGIN) || seen.some((s) => same(s, p)))) out.add(n.id);
    if (p) seen.push(p);
  });
  return out;
}

/**
 * Whether two placed steps overlap at the size steps are drawn today. Positions saved for a smaller step (a workflow
 * placed before the step grew from 240 to 288 px wide) stack the steps on each other, so the definition is laid out
 * again on open, as a never-placed one is.
 */
export function overlapping(def: EngineDefinition, types: EngineNodeType[], unplaced: Set<string> = unplacedSteps(def)): boolean {
  const boxes = new Map(definitionGraph(def, types).nodes.map((b) => [b.id, b]));
  const rs = def.nodes
    .filter((n) => n.position && !unplaced.has(n.id))
    .map((n) => ({ x: n.position!.x, y: n.position!.y, w: boxes.get(n.id)?.width ?? 0, h: boxes.get(n.id)?.height ?? 0 }));
  for (let i = 0; i < rs.length; i++)
    for (let j = i + 1; j < rs.length; j++) {
      const a = rs[i];
      const b = rs[j];
      if (a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) return true;
    }
  return false;
}

/**
 * Positions for the steps a definition does not place, the rest untouched. A never-placed definition is laid out
 * whole. In a partly placed one the unplaced steps go in one new column right of the rightmost placed step, stacked from
 * the top of the placed steps in definition order. A definition whose placed steps overlap at today's step size is
 * laid out whole too. A definition with every step placed and none overlapping comes back as the same object, so
 * opening and saving it changes nothing.
 */
export async function placeDefinition(def: EngineDefinition, types: EngineNodeType[]): Promise<EngineDefinition> {
  if (neverPlaced(def)) return applyLayout(def, await layoutDefinition(def, types));
  const unplaced = unplacedSteps(def);
  if (overlapping(def, types, unplaced)) return applyLayout(def, await layoutDefinition(def, types));
  if (unplaced.size === 0) return def;
  return placeInNewColumn(def, types, unplaced);
}

function placeInNewColumn(def: EngineDefinition, types: EngineNodeType[], unplaced: Set<string>): EngineDefinition {
  const boxes = new Map(definitionGraph(def, types).nodes.map((b) => [b.id, b]));
  const placed = def.nodes.filter((n) => !unplaced.has(n.id));
  const pos = (n: EngineNode) => n.position ?? ORIGIN;
  const x = Math.max(...placed.map((n) => pos(n).x + (boxes.get(n.id)?.width ?? 0))) + COLUMN_GAP;
  let y = Math.min(...placed.map((n) => pos(n).y));
  const at = new Map<string, Point>();
  for (const n of def.nodes) {
    if (!unplaced.has(n.id)) continue;
    at.set(n.id, { x, y });
    y += (boxes.get(n.id)?.height ?? 0) + ROW_GAP;
  }
  return { ...def, nodes: def.nodes.map((n) => (at.has(n.id) ? { ...n, position: at.get(n.id) } : n)) };
}
