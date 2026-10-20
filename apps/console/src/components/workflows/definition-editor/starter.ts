import type { EngineDefinition } from '@/lib/types/engine';

/**
 * The smallest definition every check passes: a request trigger wired to an end. The id is the name as a slug plus a
 * random suffix, because publishing under an id that exists adds a version to that workflow instead of creating one.
 */
export function starterDefinition(name: string, description: string, suffix = Math.random().toString(36).slice(2, 8)): EngineDefinition {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 48);
  const id = `${/^[a-z]/.test(slug) ? slug : `wf_${slug}`}_${suffix}`.replace(/_+/g, '_');
  return {
    schemaVersion: 2,
    id,
    name,
    description,
    nodes: [
      { id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request', position: { x: 0, y: 0 } },
      { id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: { outcome: 'done' }, position: { x: 440, y: 0 } },
    ],
    connections: [{ from: { node: 'start', port: 'payload' }, to: { node: 'done', port: 'in' } }],
  };
}
