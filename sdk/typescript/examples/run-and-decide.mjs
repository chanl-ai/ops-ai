// Starts a run of a workflow that waits on a person, waits for the task, decides it as the reviewer, and waits for
// the run to finish, through the TypeScript SDK. `make sdk-check` runs it on the team the Python seed example made:
//   OPS_EXAMPLE_TEAM=... OPS_EXAMPLE_WORKFLOW=... OPS_EXAMPLE_EMAIL=... OPS_EXAMPLE_REVIEWER=... node examples/run-and-decide.mjs
import { OpsAI } from '../dist/index.js';

const env = process.env;
const ports = { platform: 8710, agents: 8700, tools: 8720, kb: 8740, files: 8750, documents: 8760 };
const conn = env.OPS_BASE_URL
  ? { baseUrl: env.OPS_BASE_URL }
  : { baseUrl: 'http://127.0.0.1', services: Object.fromEntries(Object.entries(ports).map(([s, p]) => [s, `http://127.0.0.1:${p}`])) };
const team = env.OPS_EXAMPLE_TEAM;
const lead = await OpsAI.signIn(env.OPS_EXAMPLE_EMAIL, env.OPS_EXAMPLE_PASSWORD, { ...conn, team });
const reviewer = await OpsAI.signIn(env.OPS_EXAMPLE_REVIEWER, env.OPS_EXAMPLE_PASSWORD, { ...conn, team });
const started = await lead.runs.start(env.OPS_EXAMPLE_WORKFLOW, { input: { cardholder: 'Sam Example', amount: '80.00' } });
let run = await lead.runs.wait(started.runId, { timeoutMs: 120_000 });
if (run.status !== 'waiting' || !run.taskId) throw new Error(`run-and-decide: expected a waiting run, got ${run.status}`);
console.log(`  run waiting            ${run.id} on task ${run.taskId}`);
await reviewer.tasks.decide(run.taskId, 'reject', { reason: 'Outside the dispute window.' });
run = await lead.runs.wait(started.runId, { timeoutMs: 120_000 });
if (run.status !== 'succeeded' || run.outcome !== 'declined') throw new Error(`run-and-decide: expected declined, got ${run.status}/${run.outcome}`);
console.log(`  run finished           ${run.id} succeeded, outcome ${run.outcome}`);
console.log('run-and-decide: done');
