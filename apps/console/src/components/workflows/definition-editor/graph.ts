import type { EngineConnection, EngineDefinition, EngineNode, EngineNodeType, EnginePort, PortRule } from '@/lib/types/engine';

/** A port as the canvas draws it: the handle id is `name`, the text is `label`. */
export interface DrawnPort {
  name: string;
  label: string;
}

export const typeKey = (id: string, version: number) => `${id}@${version}`;

/** Every registered type by `id@version`, so a node resolves to exactly the version it pins. */
export function indexTypes(types: EngineNodeType[]): Map<string, EngineNodeType> {
  return new Map(types.map((t) => [typeKey(t.id, t.version), t]));
}

/** The highest version of each type, which is what the palette offers. */
export function latestTypes(types: EngineNodeType[]): EngineNodeType[] {
  const latest = new Map<string, EngineNodeType>();
  for (const t of types) {
    const seen = latest.get(t.id);
    if (!seen || t.version > seen.version) latest.set(t.id, t);
  }
  return [...latest.values()];
}

/** Latest types grouped by their `group`, groups and types sorted by label. */
export function paletteGroups(types: EngineNodeType[]): [string, EngineNodeType[]][] {
  const groups = new Map<string, EngineNodeType[]>();
  for (const t of latestTypes(types)) groups.set(t.group, [...(groups.get(t.group) ?? []), t]);
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([g, ts]) => [g, ts.sort((a, b) => a.label.localeCompare(b.label))]);
}

const drawn = (p: EnginePort): DrawnPort => ({ name: p.name, label: p.label || p.name });

export const inPorts = (type: EngineNodeType): DrawnPort[] => type.inputs.map(drawn);

/**
 * The instance's out ports. Mirrors `NodeType.output_ports` / `option_name` in ops_engine: when the type names an
 * `outputsFrom` list parameter and the node sets it to a non-empty list, each entry is a port (a string is its own
 * name; an object contributes its `name`, labelled by `label` when present). Otherwise the declared `outputs`.
 */
/**
 * Whether a setting holds the rule's value, as the engine reads it: an unset setting takes its schema default, and `"*"`
 * holds for any value set (a timeout's hours, say).
 */
function holds(type: EngineNodeType, parameters: Record<string, unknown> | undefined, rule: PortRule): boolean {
  const props = (type.parameters as { properties?: Record<string, { default?: unknown }> } | undefined)?.properties;
  const value = parameters?.[rule.parameter] ?? props?.[rule.parameter]?.default;
  if (rule.value === '*') return value !== undefined && value !== null && value !== '';
  return value === rule.value;
}

export function outPorts(type: EngineNodeType, parameters: Record<string, unknown> | undefined): DrawnPort[] {
  const raw = type.outputsFrom ? parameters?.[type.outputsFrom] : undefined;
  const ports: DrawnPort[] =
    Array.isArray(raw) && raw.length
      ? raw.map((o: unknown) => {
          if (o && typeof o === 'object') {
            const rec = o as { name?: unknown; label?: unknown };
            const name = typeof rec.name === 'string' ? rec.name : '';
            return { name, label: typeof rec.label === 'string' && rec.label ? rec.label : name };
          }
          return { name: String(o), label: String(o) };
        })
      : type.outputs.map(drawn);
  // The engine's output_ports: then the ports every instance has (a switch's otherwise), then an optional port (a
  // review's timeout) while its parameter holds the value; a port the settings take away goes; each name once.
  const extra = [...(type.extraOutputs ?? []), ...(type.optionalOutputs ?? []).filter((o) => holds(type, parameters, o)).map((o) => o.port)];
  for (const name of extra) if (!ports.some((p) => p.name === name)) ports.push({ name, label: name });
  const dropped = new Set((type.outputsUnless ?? []).filter((o) => holds(type, parameters, o)).map((o) => o.port));
  return ports.filter((p) => !dropped.has(p.name));
}

/**
 * A step that repeats over a list (any type whose `forEach` parameter is set) says so on the canvas: "for each records
 * from Read the file", the list's field and the step it comes from, by name. Nothing for a step that runs once.
 */
export function repeatsOver(parameters: Record<string, unknown> | undefined, nodes: EngineNode[]): string | null {
  const raw = parameters?.forEach;
  if (typeof raw !== 'string' || !raw.trim()) return null;
  // `a ?? b` reads b when a is empty; the first list is the one the step means.
  const path = raw.split('??')[0].trim();
  const m = /^\$\.nodes\.([^.]+)\.out(?:\.(.+))?$/.exec(path);
  if (m) {
    // The step's name says where the list comes from; its output field (`edited`, `records`) is engine detail.
    const from = nodes.find((n) => n.id === m[1]);
    return `for each item from ${from?.name || m[1]}`;
  }
  const input = /^\$\.input\.(.+)$/.exec(path);
  return `for each ${input ? `${input[1].split('.').pop()} in the input` : 'item of a list'}`;
}

export const connectionId = (c: EngineConnection) => `${c.from.node}:${c.from.port}->${c.to.node}:${c.to.port}`;

/** A node id derived from the type's last segment, numbered when taken: `humanReview`, `humanReview_2`. */
export function uniqueNodeId(typeId: string, nodes: EngineNode[]): string {
  const base = (typeId.split('.').pop() || 'node').replace(/[^A-Za-z0-9_]/g, '_');
  const taken = new Set(nodes.map((n) => n.id));
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
}

// Wider and taller than a drawn node (about 360 by 170 px), so laid-out nodes never overlap.
const COL = 440;
const ROW = 220;

/**
 * Positions for nodes the definition does not place: left to right by longest path from a node with no incoming
 * connection, stacked within a column in definition order. A cycle is cut where it is first re-entered.
 */
export function layeredPositions(def: EngineDefinition): Record<string, { x: number; y: number }> {
  const ids = def.nodes.map((n) => n.id);
  const incoming = new Map(ids.map((id) => [id, [] as string[]]));
  for (const c of def.connections) incoming.get(c.to.node)?.push(c.from.node);
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const depthOf = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const parents = (incoming.get(id) ?? []).filter((p) => incoming.has(p));
    const d = parents.length ? Math.max(...parents.map(depthOf)) + 1 : 0;
    visiting.delete(id);
    depth.set(id, d);
    return d;
  };
  const rows = new Map<number, number>();
  const out: Record<string, { x: number; y: number }> = {};
  for (const id of ids) {
    const d = depthOf(id);
    const r = rows.get(d) ?? 0;
    rows.set(d, r + 1);
    out[id] = { x: d * COL, y: r * ROW };
  }
  return out;
}

/**
 * Fills in a position for every node the definition does not place, so moving one never moves the rest. The server
 * stores a missing position as {x: 0, y: 0}, so a definition whose nodes all share one position was never placed and
 * is laid out whole.
 */
export function withPositions(def: EngineDefinition): EngineDefinition {
  const at = (n: EngineNode) => (n.position ? `${n.position.x},${n.position.y}` : '');
  const unplaced = def.nodes.length > 1 && new Set(def.nodes.map(at)).size === 1;
  if (!unplaced && def.nodes.every((n) => n.position)) return def;
  const laid = layeredPositions(def);
  return { ...def, nodes: def.nodes.map((n) => (n.position && !unplaced ? n : { ...n, position: laid[n.id] })) };
}
