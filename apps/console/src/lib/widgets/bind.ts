// A widget template filled with data for the authoring preview (c-082): the same rules as agents-service's
// ops_agent_kernel.layout.fill, minus the schema check, which the service runs on save. Pure, so the preview and its
// tests need no service. Relative imports: the tests run under `node --test`, which does not resolve the `@/` alias.
import type { LayoutNode, TemplateNode } from '../types/widgets';

const REQUIRED: Partial<Record<LayoutNode['type'], string[]>> = {
  title: ['text'],
  text: ['text'],
  caption: ['text'],
  badge: ['text'],
  metric: ['label', 'value'],
  table: ['rows'],
  chart: ['rows', 'x', 'y'],
  keyValue: ['items'],
  list: ['items'],
  button: ['label', 'reply'],
};
const HOLDS = new Set(['card', 'row', 'column']);

/** The value at a JSON Pointer in `data`, or undefined when the data has nothing there. */
export function pointer(data: unknown, path: string): unknown {
  if (path === '') return data;
  let cur: unknown = data;
  for (const raw of path.slice(1).split('/')) {
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (Array.isArray(cur) && /^\d+$/.test(key)) cur = cur[Number(key)];
    else if (cur && typeof cur === 'object' && key in cur) cur = (cur as Record<string, unknown>)[key];
    else return undefined;
  }
  return cur;
}

function bound(v: unknown, data: unknown): unknown {
  if (Array.isArray(v)) return v.map((x) => bound(x, data));
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if (Object.keys(o).length === 1 && typeof o.$bind === 'string') return pointer(data, o.$bind);
    return Object.fromEntries(Object.entries(o).map(([k, x]) => [k, bound(x, data)]));
  }
  return v;
}

/**
 * The template's tree with every `{ "$bind": pointer }` replaced from `data`. A node whose required field the data
 * left out is dropped, a badge's `tones` lookup picks its tone, and null comes back when nothing is left to show.
 */
export function fillTemplate(tree: TemplateNode, data: unknown): LayoutNode | null {
  const walk = (n: TemplateNode): LayoutNode | null => {
    const node = bound(n, data) as Record<string, unknown>;
    if ((REQUIRED[node.type as LayoutNode['type']] ?? []).some((f) => node[f] === undefined || node[f] === null)) return null;
    if (node.type === 'badge' && node.tones && typeof node.tones === 'object') {
      const { tones, ...rest } = node;
      return { ...rest, tone: (tones as Record<string, string>)[String(node.text)] ?? node.tone ?? 'neutral' } as LayoutNode;
    }
    if (HOLDS.has(String(node.type))) {
      const kids = ((n.children ?? []) as TemplateNode[]).map(walk).filter((c): c is LayoutNode => c !== null);
      return { ...node, children: kids } as LayoutNode;
    }
    return node as LayoutNode;
  };
  return walk(tree);
}
