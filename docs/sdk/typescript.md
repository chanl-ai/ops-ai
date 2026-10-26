# TypeScript SDK

Status: current. Built and tested against the local stack; not yet published to npm, so build it from the
repository until the first release.

Call Ops AI from TypeScript or JavaScript on Node 20 or newer: start workflow runs and wait for them, decide the human
tasks they open, and work with agents, cases, tools, knowledge and files, as one person acting in one team. Every
operation's arguments and answer are typed from the API reference.

## Install

```bash
pnpm --filter @chanl-ai/ops-ai build && npm install ./sdk/typescript   # until the package is on npm
```

## Connect

Create an API key in the console under Settings > Team > API keys, in the team the script acts in.

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ apiKey: 'ok_...', baseUrl: 'https://ops.example.com', team: 'team_claims' });
```

The options `baseUrl`, `apiKey` and `team` fall back to `OPS_BASE_URL`, `OPS_API_KEY` and `OPS_TEAM`. On a local stack
with no proxy, pass `services: { agents: 'http://127.0.0.1:8700', ... }`.

## Run a workflow and decide its task

```ts
const started = await ops.runs.start('wf_card_dispute', { input: { cardholder: 'Jordan Example', amount: '120.00' } });
let run = await ops.runs.wait(started.runId);       // when the run ends or stops at a human task
if (run.taskId) {
  await ops.tasks.decide(run.taskId, 'approve', { reason: "Within the lead's limit." });
  run = await ops.runs.wait(started.runId);
}
console.log(run.status, run.outcome);
```

`for await (const event of ops.runs.stream(runId))` gives the run's events as they happen.

## What the client offers

The same attributes as the [Python SDK](python.md#what-the-client-offers), with `list()` as an async iterator and
`raw.<service>.<operation>({ path, query, body })` for every other public operation.

## Errors

A refused call rejects with a subclass of `OpsError` carrying `status`, `code`, `message` and `requestId`, the same
classes as the Python SDK. Reads are retried twice on 429 and 5xx; a write only when its route takes an idempotency
key and the call sends one.

## Where it lives

The package is `sdk/typescript`; `src/generated` is written by `sdk/generate.py` with openapi-typescript. The example
`sdk/typescript/examples/run-and-decide.mjs` starts and decides a run.
