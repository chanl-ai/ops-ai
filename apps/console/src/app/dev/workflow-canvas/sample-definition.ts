import type { EngineDefinition, EngineNode } from '@/lib/types/engine';

// A ten-step wire review built only from registered step types, so the server's real check validates it. Positions
// are laid out by hand, one column per step in the order they run.
const COL = 290;
const ROW = 150;
const at = (col: number, row: number) => ({ x: col * COL, y: row * ROW });

const NODES: EngineNode[] = [
  {
    id: 'start',
    type: 'ops.trigger.request',
    typeVersion: 1,
    name: 'Wire flagged',
    parameters: {
      inputSchema: {
        type: 'object',
        properties: {
          wire_id: { type: 'string', description: 'The outbound wire' },
          customer_id: { type: 'string', description: 'Who sent it' },
          amount: { type: 'number', description: 'In the account currency' },
        },
        required: ['wire_id', 'customer_id', 'amount'],
      },
    },
    position: at(0, 1),
  },
  {
    id: 'customer',
    type: 'ops.action.tool',
    typeVersion: 1,
    name: 'Look up the customer',
    parameters: { operation: 'get_customer', input: { customer_id: '$.input.customer_id' } },
    position: at(1, 1),
  },
  {
    id: 'assess',
    type: 'ops.ai.agent',
    typeVersion: 1,
    name: 'Assess the wire',
    parameters: {
      agent: 'ag_fraud',
      prompt: 'Assess this outbound wire for fraud against the customer record. Answer with a risk from 0 to 1 and the reason.',
      input: { wire_id: '$.input.wire_id', amount: '$.input.amount', customer: '$.nodes.customer.out' },
      outputSchema: { type: 'object', properties: { risk: { type: 'number' }, reason: { type: 'string' } }, required: ['risk', 'reason'] },
    },
    position: at(2, 1),
  },
  {
    id: 'risky',
    type: 'ops.flow.if',
    typeVersion: 1,
    name: 'Risk 0.7 or more?',
    parameters: { conditions: [{ left: '$.nodes.assess.out.risk', op: 'gte', right: 0.7 }], combine: 'all' },
    position: at(3, 1),
  },
  {
    id: 'review',
    type: 'ops.flow.humanReview',
    typeVersion: 1,
    name: 'Hold the wire?',
    parameters: { title: 'Hold this wire', summary: '$.nodes.assess.out.reason', approves: 'hold' },
    position: at(4, 0.4),
  },
  {
    id: 'hold',
    type: 'ops.action.tool',
    typeVersion: 1,
    name: 'Place the hold',
    parameters: { operation: 'place_wire_hold', input: { wire_id: '$.input.wire_id' }, approvedBy: 'review' },
    position: at(5, 0.2),
  },
  {
    id: 'record',
    type: 'ops.data.set',
    typeVersion: 1,
    name: 'Record the decision',
    parameters: { values: { wire_id: '$.input.wire_id', decision: 'held', reason: '$.nodes.assess.out.reason' } },
    position: at(6, 0.2),
  },
  { id: 'held', type: 'ops.flow.end', typeVersion: 1, name: 'Held', parameters: { outcome: 'held', output: '$.nodes.record.out' }, position: at(7, 0.2) },
  { id: 'released', type: 'ops.flow.end', typeVersion: 1, name: 'Released', parameters: { outcome: 'released' }, position: at(5, 1.6) },
  { id: 'failed', type: 'ops.flow.end', typeVersion: 1, name: 'Needs a person', parameters: { outcome: 'needs_a_person' }, position: at(4, 2.4) },
];

const link = (from: string, port: string, to: string) => ({ from: { node: from, port }, to: { node: to, port: 'in' } });

export const SAMPLE_DEFINITION: EngineDefinition = {
  schemaVersion: 2,
  id: 'wire_hold_review',
  name: 'Wire hold review',
  description: 'A flagged outbound wire is assessed, and a risky one is held once a person approves.',
  nodes: NODES,
  connections: [
    link('start', 'payload', 'customer'),
    link('customer', 'ok', 'assess'),
    link('customer', 'refused', 'failed'),
    link('customer', 'error', 'failed'),
    link('assess', 'ok', 'risky'),
    link('assess', 'error', 'failed'),
    link('risky', 'true', 'review'),
    link('risky', 'false', 'released'),
    link('review', 'approve', 'hold'),
    link('review', 'reject', 'released'),
    link('hold', 'ok', 'record'),
    link('hold', 'refused', 'failed'),
    link('hold', 'error', 'failed'),
    link('record', 'out', 'held'),
  ],
};

/** The same workflow with the hold step's operation cleared, so the server's check refuses it. */
export const BROKEN_DEFINITION: EngineDefinition = {
  ...SAMPLE_DEFINITION,
  nodes: NODES.map((n) => (n.id === 'hold' ? { ...n, parameters: { input: { wire_id: '$.input.wire_id' }, approvedBy: 'review' } } : n)),
};

/** A new workflow before its first step. */
export const EMPTY_DEFINITION: EngineDefinition = { schemaVersion: 2, id: 'new_workflow', name: 'New workflow', nodes: [], connections: [] };
