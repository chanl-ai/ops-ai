// Edits to a widget template's layout tree by path (c-110): the layout form changes one block at a time and the tree
// stays the one value the preview, the JSON view and the save all read. A path is the child indexes from the root.
// Relative imports: the tests run under `node --test`, which does not resolve the `@/` alias.
import type { LayoutNode, TemplateNode } from '../types/widgets';

export type NodePath = number[];
export type BlockType = LayoutNode['type'];

/** Blocks that hold other blocks. */
export const CONTAINERS = new Set<BlockType>(['card', 'row', 'column']);

const kids = (n: TemplateNode): TemplateNode[] => (Array.isArray(n.children) ? (n.children as TemplateNode[]) : []);

export function nodeAt(root: TemplateNode, path: NodePath): TemplateNode | undefined {
  let cur: TemplateNode | undefined = root;
  for (const i of path) cur = cur ? kids(cur)[i] : undefined;
  return cur;
}

/** The tree with the node at `path` replaced by `fn(node)`; `fn` returning null removes it (never the root). */
export function updateAt(root: TemplateNode, path: NodePath, fn: (n: TemplateNode) => TemplateNode | null): TemplateNode {
  if (path.length === 0) return fn(root) ?? root;
  const [i, ...rest] = path;
  const children = kids(root);
  const child = children[i];
  if (!child) return root;
  const next = rest.length ? updateAt(child, rest, fn) : fn(child);
  return { ...root, children: next === null ? children.filter((_, n) => n !== i) : children.map((c, n) => (n === i ? next : c)) };
}

export const removeAt = (root: TemplateNode, path: NodePath) => updateAt(root, path, () => null);

/** Appends `node` to the container at `path`. */
export const appendChild = (root: TemplateNode, path: NodePath, node: TemplateNode) => updateAt(root, path, (n) => ({ ...n, children: [...kids(n), node] }));

/** Moves the node at `path` one place up (-1) or down (+1) among its siblings; out of range leaves the tree as it is. */
export function moveAt(root: TemplateNode, path: NodePath, delta: -1 | 1): TemplateNode {
  if (!path.length) return root;
  const parent = path.slice(0, -1);
  const i = path[path.length - 1];
  return updateAt(root, parent, (n) => {
    const c = [...kids(n)];
    const j = i + delta;
    if (j < 0 || j >= c.length) return n;
    [c[i], c[j]] = [c[j], c[i]];
    return { ...n, children: c };
  });
}

/** A new block of `type` with every field the catalogue requires, so it previews at once and saves without refusal. */
export function blankBlock(type: BlockType): TemplateNode {
  switch (type) {
    case 'card':
      return { type, title: 'New card', children: [] };
    case 'row':
    case 'column':
      return { type, gap: 'md', children: [] };
    case 'title':
    case 'text':
    case 'caption':
    case 'badge':
      return { type, text: 'Text' };
    case 'metric':
      return { type, label: 'Label', value: 0 };
    case 'table':
      return { type, rows: [], columns: [] };
    case 'chart':
      return { type, rows: [], x: 'x', y: ['y'], kind: 'line' };
    case 'keyValue':
      return { type, items: [{ label: 'Label', value: 'Value' }] };
    case 'list':
      return { type, items: [] };
    case 'button':
      return { type, label: 'Button', reply: { text: 'Do it' } };
    case 'image':
      return { type, alt: 'Image' };
    default:
      return { type };
  }
}

/** Changes a block's type, keeping its children when both types hold blocks and the fields the two types share. */
export function retype(n: TemplateNode, type: BlockType): TemplateNode {
  const fresh = blankBlock(type);
  const shared = Object.fromEntries(Object.entries(n).filter(([k]) => k !== 'type' && k in fresh));
  return { ...fresh, ...shared, type, ...(CONTAINERS.has(type) ? { children: kids(n) } : {}) };
}

/** `{ $bind: "/field" }` → "field"; anything else → undefined. Only top-level fields are offered in the form. */
export function boundField(v: unknown): string | undefined {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const o = v as Record<string, unknown>;
    if (Object.keys(o).length === 1 && typeof o.$bind === 'string' && /^\/[^/]+$/.test(o.$bind)) return o.$bind.slice(1).replace(/~1/g, '/').replace(/~0/g, '~');
  }
  return undefined;
}

export const bindTo = (field: string) => ({ $bind: `/${field.replace(/~/g, '~0').replace(/\//g, '~1')}` });
