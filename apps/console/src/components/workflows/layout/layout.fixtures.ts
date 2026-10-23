import type { EngineDefinition } from '@/lib/types/engine';

/**
 * Positions of the six seeds whose trigger sits off the origin, as engine_workflows.json held them at 6c3706a0, before
 * the c-486 bake moved every first step to {0, 0}. The missing-position rule's first clause (a step at {0, 0} with the
 * trigger elsewhere) only has a real case in these, so the tests apply them to the current seeds.
 */
export const OFF_ORIGIN_SEEDS: Record<string, Record<string, [number, number]>> = {
  levy_read_one: {start: [0, 150], read: [280, 150], check: [560, 0], facts: [840, 150], kind: [1120, 150], person: [1400, 450], notice_terms: [1400, 0], levy_terms: [1400, 300], notice_case: [1680, 0], levy_case: [1680, 300], notify_notice: [1960, 0], notify_levy: [1960, 300], notice_done: [2240, 0], levy_done: [2240, 300], notices: [1400, 150], notices_done: [1680, 150], for_a_person: [1680, 450], failed: [2240, 600], save: [560, 70], save_for_check: [420, 155]},
  levy_mail: {mail: [0, 150], what: [280, 150], each: [560, 0], body: [560, 150], reply_check: [840, -10], ack: [840, 150], reply: [1120, 150], replied: [1400, 0], no_reply: [1400, 300], unreadable: [560, 450], failed: [1400, 450], nothing_to_reply: [1080, -10]},
  levy_files: {start: [0, 150], each: [280, 150], started: [560, 0], failed: [560, 300]},
  customer_hold: {start: [0, 300], search: [280, 300], match: [560, 300], accounts: [840, 300], facts: [1120, 300], calc: [1400, 300], enough: [1680, 300], review: [1960, 150], supervisor: [2240, 450], hold: [2240, 150], hold_by_supervisor: [2520, 450], case: [2800, 300], note: [3080, 300], notify: [3360, 300], held: [3640, 300], not_found: [840, 600], no_funds: [1960, 600], declined: [2520, 0], failed: [3640, 600]},
  attachment_record: {start: [0, 150], read: [280, 150], save: [560, 150], recorded: [840, 150], unreadable: [560, 450], failed: [840, 450]},
  complaint_triage: {mail: [0, 300], what: [280, 300], each: [560, 0], read_body: [1400, 300], combine: [1680, 300], triage: [1960, 300], urgency: [2240, 300], urgent: [2520, 150], normal: [2520, 300], low: [2520, 450], has_case: [2800, 300], add: [3080, 150], open: [3080, 450], wants_hold: [3360, 300], hold_once: [3640, 150], reply_check: [3920, 140], ack: [3920, 300], reply: [4200, 300], replied: [4480, 150], no_reply: [4480, 450], unreadable: [560, 600], failed: [4480, 600], nothing_to_reply: [4160, 140]},
};

/**
 * A 50-step workflow for the layout budget: a request trigger, then a chain of tool calls whose Ok, Refused and Error
 * ports each lead on, every third step fanning out three ways and the branches joining back, so the layout meets long
 * lines, fan-outs and joins. Built from the engine's own types (node-types.json).
 */
export function fiftySteps(): EngineDefinition {
  const nodes: EngineDefinition['nodes'] = [{ id: 'start', type: 'ops.trigger.request', typeVersion: 1, name: 'Request' }];
  const connections: EngineDefinition['connections'] = [];
  let last = 'start';
  let port = 'payload';
  let i = 0;
  while (nodes.length < 49) {
    i++;
    const id = `step_${i}`;
    nodes.push({ id, type: 'ops.action.tool', typeVersion: 1, name: `Step ${i}`, parameters: { operation: 'get_customer' } });
    connections.push({ from: { node: last, port }, to: { node: id, port: 'in' } });
    if (i % 3 === 0 && nodes.length < 47) {
      const refused = `refused_${i}`;
      const failed = `failed_${i}`;
      nodes.push({ id: refused, type: 'ops.action.tool', typeVersion: 1, name: `Retry ${i}`, parameters: { operation: 'get_customer' } });
      nodes.push({ id: failed, type: 'ops.flow.end', typeVersion: 1, name: `Failed ${i}`, parameters: { outcome: 'failed' } });
      connections.push({ from: { node: id, port: 'refused' }, to: { node: refused, port: 'in' } });
      connections.push({ from: { node: id, port: 'error' }, to: { node: failed, port: 'in' } });
      connections.push({ from: { node: refused, port: 'ok' }, to: { node: id, port: 'in' } });
    }
    last = id;
    port = 'ok';
  }
  nodes.push({ id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: { outcome: 'done' } });
  connections.push({ from: { node: last, port }, to: { node: 'done', port: 'in' } });
  return { schemaVersion: 2, id: 'fifty_steps', name: 'Fifty steps', nodes, connections };
}
