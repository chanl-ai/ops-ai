import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { OpsAI } from '../../../sdk/typescript/dist/index.js';

const folder = dirname(fileURLToPath(import.meta.url));
const definition = JSON.parse(readFileSync(resolve(folder, 'resources/workflow.json'), 'utf8'));
const valid = JSON.parse(readFileSync(resolve(folder, 'fixtures/valid.json'), 'utf8'));
const missing = JSON.parse(readFileSync(resolve(folder, 'fixtures/missing-email.json'), 'utf8'));
const expected = JSON.parse(readFileSync(resolve(folder, 'expected/accepted.json'), 'utf8'));

function client() {
  const path = resolve(folder, '.ops-profile.json');
  if (existsSync(path)) {
    const local = JSON.parse(readFileSync(path, 'utf8')).profiles.local;
    return new OpsAI({
      baseUrl: local.baseUrl,
      accessToken: local.accessToken,
      team: local.team,
      services: local.services,
    });
  }
  throw new Error('run this folder\'s setup.py on a stack first');
}

function pathOf(error) {
  const details = error && typeof error === 'object' ? error.details : undefined;
  return details && typeof details === 'object' ? details.path : undefined;
}

const ops = client();
const check = await ops.workflows.validate(definition);
if (!check.ok) {
  check.raiseForErrors();
}
const made = await ops.workflows.apply(definition);
const workflowId = made.workflowId;
const run = await ops.workflows.run(workflowId, { input: valid, mode: 'test', wait: true });
if (run.status !== expected.status || run.outcome !== expected.outcome) {
  throw new Error(`expected ${expected.status}/${expected.outcome}, got ${run.status}/${run.outcome}`);
}
try {
  await ops.workflows.run(workflowId, { input: missing, mode: 'test', wait: true });
  throw new Error('missing customerEmail was accepted');
} catch (error) {
  if (error instanceof Error && error.message === 'missing customerEmail was accepted') throw error;
  if (error.status !== 422 || error.code !== 'invalid_input' || pathOf(error) !== 'customerEmail') {
    throw new Error(`expected 422 invalid_input path customerEmail, got ${error}`);
  }
}
console.log(`accepted ${workflowId}`);
