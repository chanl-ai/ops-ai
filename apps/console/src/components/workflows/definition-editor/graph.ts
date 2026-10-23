import type { EngineConnection, EngineDefinition, EngineNode, EngineNodeType, EnginePort, PortRule } from '@/lib/types/engine';

import type { DefinitionNodeData } from './definition-node';
import { definitionNodeSize, titleLines } from '../layout/node-size.ts';

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

/** The singular of a plain English plural field name (`debtors` → `debtor`), or null when it is not one. */
function singular(field: string): string | null {
  const words = field.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ').toLowerCase();
  if (/ies$/.test(words)) return words.replace(/ies$/, 'y');
  if (/(ch|sh|x|ss)es$/.test(words)) return words.replace(/es$/, '');
  if (/[^s]s$/.test(words)) return words.replace(/s$/, '');
  return null;
}

// Output fields that are the engine's names for "the list it read", not words a person would use.
const ENGINE_LISTS = new Set(['records', 'edited', 'items', 'results', 'rows']);

/**
 * A step that repeats over a list (any type whose `forEach` parameter is set) says so on the canvas in short words that
 * fit one line: "For each attachment", "For each item from Read the file", "For each debtor in the input". Nothing for
 * a step that runs once.
 */
export function repeatsOver(parameters: Record<string, unknown> | undefined, nodes: EngineNode[]): string | null {
  const raw = parameters?.forEach;
  if (typeof raw !== 'string' || !raw.trim()) return null;
  // `a ?? b` reads b when a is empty; the first list is the one the step means.
  const path = raw.split('??')[0].trim();
  const m = /^\$\.nodes\.([^.]+)\.out(?:\.(.+))?$/.exec(path);
  if (m) {
    const field = m[2]?.split('.').pop() ?? '';
    const one = ENGINE_LISTS.has(field) ? null : singular(field);
    if (one) return `For each ${one}`;
    const from = nodes.find((n) => n.id === m[1]);
    return `For each item from ${from?.name || m[1]}`;
  }
  const input = /^\$\.input\.(.+)$/.exec(path);
  if (input) return `For each ${singular(input[1].split('.').pop() ?? '') ?? 'item'} in the input`;
  return 'For each item of a list';
}

/** The most characters of the repeat line drawn on a step; a longer one is shortened, with the whole on hover. */
export const REPEAT_LINE_MAX = 26;

/**
 * The repeat line as a step draws it on one line: the whole of it when it fits, else only what is repeated over ("For
 * each attachment in the input" becomes "For each attachment"). Counted in characters, like the title's lines.
 */
export function repeatsLine(full: string): string {
  if (full.length <= REPEAT_LINE_MAX) return full;
  return full.replace(/ (in the input|from .+|of a list)$/, '');
}

/** What a step is called on the canvas: its name, else its type's label, else its id. */
export const stepTitle = (n: EngineNode, t: EngineNodeType | undefined) => n.name || t?.label || n.id;

/**
 * What a canvas draws on a step, from the step and its type alone: the editor, the run canvas and the layout preview
 * build their nodes from it, each adding its own checks or run mark.
 */
export function definitionNodeData(n: EngineNode, t: EngineNodeType | undefined, nodes: EngineNode[]): DefinitionNodeData {
  return {
    nodeId: n.id,
    title: stepTitle(n, t),
    titleLines: titleLines(stepTitle(n, t)),
    typeLabel: t ? t.label : `${n.type} · version ${n.typeVersion}`,
    repeats: (() => {
      const full = repeatsOver(n.parameters, nodes);
      return full && repeatsLine(full);
    })(),
    repeatsFull: repeatsOver(n.parameters, nodes),
    group: t?.group ?? null,
    inputs: t ? inPorts(t) : [],
    outputs: t ? outPorts(t, n.parameters) : [],
    unknown: !t,
    hasError: false,
    typeId: n.type,
    layoutHeight: definitionNodeSize(n, t, nodes).height,
  };
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
