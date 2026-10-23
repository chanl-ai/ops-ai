// outPorts against the engine's output_ports, by failure mode: a port the engine can route a run out of but the
// canvas does not draw (a review's timeout), a port drawn that the engine never has, and the same name drawn twice.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { EngineNode, EngineNodeType } from '../../../lib/types/engine.ts';
import { outPorts, repeatsLine, repeatsOver } from './graph.ts';

// ops.flow.humanReview as GET /v1/engine/node-types lists it.
const review = {
  id: 'ops.flow.humanReview',
  outputs: [{ name: 'approve' }, { name: 'reject' }],
  outputsFrom: 'options',
  optionalOutputs: [{ parameter: 'onTimeout', value: 'expire', port: 'timeout' }],
} as unknown as EngineNodeType;

const names = (params: Record<string, unknown> | undefined) => outPorts(review, params).map((p) => p.name);

test('a review set to expire draws its timeout port after its options', () => {
  assert.deepEqual(names({ onTimeout: 'expire' }), ['approve', 'reject', 'timeout']);
  assert.deepEqual(names({ onTimeout: 'expire', options: [{ name: 'pay' }, { name: 'hold' }] }), ['pay', 'hold', 'timeout']);
});

test('a review that does not expire has no timeout port', () => {
  assert.deepEqual(names({ onTimeout: 'wait' }), ['approve', 'reject']);
  assert.deepEqual(names(undefined), ['approve', 'reject']);
});

// ops.action.workflow (c-263): waiting for the runs swaps `started` for `done`, and any timeout adds `timeout`.
const runWorkflow = {
  id: 'ops.action.workflow',
  outputs: [{ name: 'started' }, { name: 'error' }],
  outputsFrom: null,
  parameters: { properties: { wait: { type: 'boolean', default: false } } },
  optionalOutputs: [
    { parameter: 'wait', value: true, port: 'done' },
    { parameter: 'timeoutHours', value: '*', port: 'timeout' },
  ],
  outputsUnless: [{ parameter: 'wait', value: true, port: 'started' }],
} as unknown as EngineNodeType;
const runPorts = (params: Record<string, unknown> | undefined) => outPorts(runWorkflow, params).map((p) => p.name);

test('a Run workflow step that waits ends at done instead of started, and gets timeout once a timeout is set', () => {
  assert.deepEqual(runPorts(undefined), ['started', 'error']);
  assert.deepEqual(runPorts({ wait: true }), ['error', 'done']);
  assert.deepEqual(runPorts({ wait: true, timeoutHours: 24 }), ['error', 'done', 'timeout']);
  assert.deepEqual(runPorts({ wait: false, timeoutHours: '' }), ['started', 'error']);
});

// ops.flow.wait (c-277): the error port exists only when waiting until a mapped time.
const wait = { id: 'ops.flow.wait', outputs: [{ name: 'out' }], outputsFrom: null, optionalOutputs: [{ parameter: 'mode', value: 'until', port: 'error' }] } as unknown as EngineNodeType;

test('a Wait step has an error port only when it waits until a time', () => {
  assert.deepEqual(outPorts(wait, { mode: 'duration', seconds: 60 }).map((p) => p.name), ['out']);
  assert.deepEqual(outPorts(wait, { mode: 'until', until: '$.input.due' }).map((p) => p.name), ['out', 'error']);
});

// ops.flow.switch: a port per case, then otherwise, which every switch has.
const sw = { id: 'ops.flow.switch', outputs: [{ name: 'otherwise' }], outputsFrom: 'cases', extraOutputs: ['otherwise'] } as unknown as EngineNodeType;

test('a switch draws its cases in order and otherwise last, once', () => {
  const cases = [{ name: 'attachments', conditions: [] }, { name: 'body_only', conditions: [] }];
  assert.deepEqual(outPorts(sw, { cases }).map((p) => p.name), ['attachments', 'body_only', 'otherwise']);
  assert.deepEqual(outPorts(sw, { cases: [] }).map((p) => p.name), ['otherwise']);
});

test('an option already named timeout is drawn once', () => {
  assert.deepEqual(names({ onTimeout: 'expire', options: ['ok', 'timeout'] }), ['ok', 'timeout']);
});

test('a step that repeats over a list names the step it comes from, never its output field; a step that runs once says nothing', () => {
  const nodes = [{ id: 'read', name: 'Read the file' }] as EngineNode[];
  assert.equal(repeatsOver({ forEach: '$.nodes.read.out.records' }, nodes), 'For each item from Read the file');
  assert.equal(repeatsOver({ forEach: '$.input.debtors' }, nodes), 'For each debtor in the input');
  assert.equal(repeatsOver({ forEach: '$.nodes.read.out.attachments' }, nodes), 'For each attachment');
  assert.equal(repeatsOver({ forEach: '$.input.policies' }, nodes), 'For each policy in the input');
  assert.equal(repeatsOver({ forEach: '$.input.boxes' }, nodes), 'For each box in the input');
  assert.equal(repeatsOver({ forEach: '$.input.data' }, nodes), 'For each item in the input');
  // A fallback reads the first list; nothing of the path syntax reaches the canvas.
  assert.equal(repeatsOver({ forEach: '$.nodes.read.out.edited ?? $.nodes.read.out.records' }, nodes), 'For each item from Read the file');
  assert.equal(repeatsOver({ forEach: '' }, nodes), null);
  assert.equal(repeatsOver({ workflow: 'levy_case' }, nodes), null);
});

test('a repeat line too long for a step keeps what it repeats over, so it is never cut off', () => {
  assert.equal(repeatsLine('For each attachment in the input'), 'For each attachment');
  assert.equal(repeatsLine('For each item from Check the read'), 'For each item');
  assert.equal(repeatsLine('For each item from Read'), 'For each item from Read');
});
