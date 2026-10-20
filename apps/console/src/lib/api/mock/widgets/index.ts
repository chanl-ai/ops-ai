import { ApiError } from '../../contract';
import { pageOptions } from '../../options';
import type { WidgetsApi } from '../../widgets-contract';
import { list, respond } from '../runtime';
import type { TemplateNode, WidgetTemplate, WidgetTemplateInput } from '@/lib/types/widgets';

import seeded from './templates.json';

// The catalogue the kernel accepts (ops_agent_kernel.layout.CATALOGUE); a node outside it is refused on save, as the
// service will refuse it.
const CATALOGUE = new Set(['card', 'row', 'column', 'title', 'text', 'caption', 'badge', 'metric', 'table', 'chart', 'keyValue', 'list', 'button', 'divider', 'image']);
const HOLDS = new Set(['card', 'row', 'column']);

/** Why a template cannot be saved: an unknown primitive, or a `$bind` pointer to a field the data schema lacks. */
function problem(input: WidgetTemplateInput): string | null {
  if (!input.name.trim()) return 'Name the widget.';
  if (!input.useWhen.trim()) return 'Say when the agent should use it.';
  if ((input.dataSchema as { type?: string }).type !== 'object') return 'The data schema must be a JSON Schema with type object.';
  const props = Object.keys(((input.dataSchema as { properties?: object }).properties ?? {}) as object);
  const walk = (n: unknown, at: string): string | null => {
    if (!n || typeof n !== 'object' || Array.isArray(n)) return `${at || '/'}: must be a node with a type.`;
    const node = n as TemplateNode;
    if (!CATALOGUE.has(node.type)) return `${at || '/'}: type "${node.type}" is not in the catalogue.`;
    for (const [k, v] of Object.entries(node)) {
      if (v && typeof v === 'object' && '$bind' in (v as object)) {
        const top = String((v as { $bind: string }).$bind).split('/')[1];
        if (!props.includes(top)) return `${at}/${k}: binds /${top}, which the data schema does not define.`;
      }
    }
    if (HOLDS.has(node.type)) {
      const kids = (node.children ?? []) as unknown[];
      for (const [i, c] of kids.entries()) {
        const why = walk(c, `${at}/children/${i}`);
        if (why) return why;
      }
    }
    return null;
  };
  return walk(input.tree, '');
}

const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'widget';

/** Widget templates in memory with the service's rules: catalogue-only trees, bindings into the schema, versions. */
export function createWidgetsMock(deps: { me: string }): WidgetsApi {
  const rows: WidgetTemplate[] = structuredClone(seeded) as unknown as WidgetTemplate[];
  const latest = () => [...new Map(rows.map((w) => [w.widgetId, w])).values()].sort((a, b) => a.name.localeCompare(b.name));
  const newest = (id: string) => {
    const found = rows.filter((w) => w.widgetId === id).sort((a, b) => b.version - a.version)[0];
    if (!found) throw new ApiError(`Widget ${id} not found`, 404);
    return found;
  };
  const save = (base: Omit<WidgetTemplate, 'status' | 'updatedBy' | 'updatedAt'>) => {
    const row: WidgetTemplate = { ...base, status: 'draft', updatedBy: deps.me, updatedAt: new Date().toISOString() };
    rows.push(row);
    return row;
  };
  return {
    list: () => respond(() => latest()),
    get: (id) => respond(() => newest(id)),
    page: (p) => respond((m) => list(latest(), p, { text: (w) => w.name, value: () => '', facetKeys: [] }, m)),
    options: (p, granted) =>
      respond(() =>
        pageOptions(
          latest()
            .filter((w) => (w.status ?? 'published') === 'published')
            .map((w) => {
              const missing = (w.requiresTools ?? []).filter((t) => !granted.includes(t));
              return { id: w.widgetId, label: w.name, hint: `v${w.version} · ${w.useWhen}`, disabled: missing.length ? `Needs ${missing.join(', ')}; grant it first.` : null };
            }),
          p,
        ),
      ),
    create: (input) =>
      respond(() => {
        const why = problem(input);
        if (why) throw new ApiError(why, 422);
        let id = slug(input.name);
        while (rows.some((w) => w.widgetId === id)) id = `${id}-2`;
        return save({ widgetId: id, version: 1, ...input });
      }),
    update: (id, input) =>
      respond(() => {
        const why = problem(input);
        if (why) throw new ApiError(why, 422);
        const cur = newest(id);
        // A draft is edited in place; a published version stays as it was and the edit becomes the next version.
        if (cur.status === 'draft') {
          Object.assign(cur, input, { updatedBy: deps.me, updatedAt: new Date().toISOString() });
          return cur;
        }
        return save({ widgetId: id, version: cur.version + 1, ...input });
      }),
    requestPublish: (id, version) =>
      respond(() => {
        const cur = newest(id);
        if (cur.version !== version) throw new ApiError(`Version ${version} is not the newest draft.`, 409);
        // In the mock the second person's approval is immediate, as dev auto-approval is on the service.
        cur.status = 'published';
        return cur;
      }),
    retire: (id, reason) =>
      respond(() => {
        if (!reason.trim()) throw new ApiError('Say why the widget is retired.', 400);
        const cur = newest(id);
        cur.status = 'deprecated';
        return cur;
      }),
  };
}
