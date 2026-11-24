# TypeScript SDK

Status: current, version 1.0.0.

Call Ops AI from TypeScript or JavaScript on Node 20 or newer: start workflow runs and wait for them, decide the human
tasks they open, and work with agents, cases, tools, knowledge and files, as one person acting in one team. Every
operation's arguments and answer are typed from the API reference.

## Install

```bash
npm install @chanl-ai/ops-ai
```

The package is not on the public npm registry yet (planned); install it from your company's registry, or build it
from a clone of the repository.

## Connect

Create an API key in the console under Settings > Team > API keys, in the team the script acts in.

```ts
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ apiKey: 'ok_...', baseUrl: 'https://ops.example.com', team: 'team_claims' });
```

The options `baseUrl`, `apiKey` and `team` fall back to `OPS_BASE_URL`, `OPS_API_KEY` and `OPS_TEAM`. On an install
with no proxy in front, pass `services: { agents: '<address>', ... }` with each area's own address.

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
`raw.<service>.<operation>({ path, query, body })` for every other public operation. The Apps area's verbs are camel
case and take their options as an object: `apps.turnOn(app, fields)`, `apps.addCustom(kind, name, { baseAddress })`,
`credentials.set(app, { clientId, clientSecret })`, `accounts.makeDefault(account)`, `accounts.setKey(account, key)`,
`tools.run(app, tool, input, { real })`. The setup words are camel case too: `tools.importOpenapi(module, specUrl, operations)`, `tools.createModule(name, displayName)`, `tools.decideReview(review, decision)`, `tools.runModule(module, tool, input)`, `secrets.create(name, value)`, `egress.allowHost(host)`, `policies.set(key, value)`, `files.watches.add(name, { plugin, source, values })`, `files.watches.check(id, { wait })`, `files.watches.events(id, { after })`, `agents.grantTools(id, toolIds)`, `agents.references(search, forAgent)`, `agents.addReference(id, kind, refId)`, `agents.publishCheck(id)`, `tasks.approve(task, { password })`, `workflows.batches(workflowId, { sortOrder })`, `workflows.getBatch(batchId)`.

## Paging and filters

The shared query is `page`, `pageSize` (at most 50), `search`, `sortBy`, `sortOrder` (`asc` or `desc`), `ids` and the
list's own filters, which take an array. The nouns' `list` passes them on and follows every page. A `raw` operation
returns one page with `data`, `pagination` and `facets`; read `pagination.hasNext` to go on. The query and the reply
are described on the [HTTP API](../reference/http-api.md#how-it-works) page.

```ts
const page = await ops.raw.agents.agents_list_agents({ query: { page: 1, pageSize: 20, sortBy: 'name', sortOrder: 'asc', search: 'claims' } });
for (const agent of page.data) console.log(agent.name);
if (page.pagination.hasNext) {
  const more = await ops.raw.agents.agents_list_agents({ query: { page: 2, pageSize: 20, sortBy: 'name', sortOrder: 'asc', search: 'claims' } });
}
```

## Knowledge, templates and connectors

The same words as the [Python SDK](python.md#knowledge-templates-and-connectors), camel case:

```ts
const base = await ops.knowledge.addBase('Branch procedures', { owner: 'branch.ops@harborpine.example' });
const source = await ops.knowledge.addSource('Policies', [base.id]);
await ops.knowledge.push(source.id, 'fees/overdraft', { title: 'Overdraft fees', text: 'Fees are waived on the first day.' });

const made = await ops.templates.install('plugin:opsai.starters:doc-coauthoring');

const start = await ops.me.connectors.connect('Person desk'); // open start.authorizeUrl in a browser
await ops.me.connectors.finish(state, code);
const accounts = await ops.me.connectors.accounts();
```

## Saved profile

`new OpsAI({ profile: 'builder' })` reads the sign-in `opsai login` saved under that name; without `profile` it reads the
current one. Options you pass win over `OPS_BASE_URL`, `OPS_API_KEY` and `OPS_TEAM`, which win over the saved profile; a
caller who passes its own `apiKey` is not given the saved person's token.

Moving from 0.1.0: see [Upgrading to 1.0.0](upgrading.md).

## Errors

A refused call rejects with a subclass of `OpsError` carrying `status`, `code`, `message`, `requestId` and `details`, the
same classes as the [Python SDK](python.md#errors). The fields come from the API's one error body, described on the [HTTP API](../reference/http-api.md#how-it-works) page.
Reads are retried twice on 429 and 5xx; a write only when its route takes an idempotency key and the call sends one.

```ts
import { NotFound } from '@chanl-ai/ops-ai';

try {
  await ops.agents.get('agt_missing');
} catch (e) {
  if (e instanceof NotFound) console.log(e.status, e.code, e.requestId);
}
```

## Next

<!-- site: cards -->
- **[Python SDK](python.md)**: Every attribute and verb, with the Python spelling.
- **[HTTP API](../reference/http-api.md)**: The routes under every call, for `raw` operations.
- **[Upgrading to 1.0.0](upgrading.md)**: Paging, closed bodies and the one error format.
