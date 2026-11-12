# An agent with three tools

Status: current. Layers: ui, sdk and cli.

| Use case | |
|---|---|
| Id | `uc-086` |
| Area | Agents |
| Runs | Python, TypeScript, CLI; console steps in their own script |
| Run it | `make usecase-test UC=uc-086` |


The import-to-call path in one run, as the seeded people, in the console: the bank's keys stored as secrets, its OpenAPI
document imported, reviewed and published, a second version published, the reads tried and granted to an agent, a
chat write held until a second person approves it, and the call log naming who asked, who approved and how each call
ended. The design is [tool lifecycle](../../architecture/tool-lifecycle.md). It replaces uc-055 as the card's gate;
uc-055's last step belongs to the agent page.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder takes a bank API to an agent that reads at once | ui | 1-8 | 6 |
| S2 | A write is held until a second person approves, then runs once | ui | 9-10 | 10 |
| S3 | The call log names the agent, the approver and the outcome | ui | 11-12 | 11 |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| James Richardson, who builds the agent | Builder | the `builder` profile |
| Maya Okafor, who approves the write | Approver | the `approver` profile |
| Sam Adeyemi, Security admin | Security admin | the `security` profile |

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI

security = OpsAI(profile="security")
builder = OpsAI(profile="builder")
approver = OpsAI(profile="approver")
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';

import { OpsAI } from '@chanl-ai/ops-ai';

const security = new OpsAI({ profile: 'security' });
const builder = new OpsAI({ profile: 'builder' });
const approver = new OpsAI({ profile: 'approver' });
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=builder
```

## Steps

### 1. Allow the bank's host and range

```python tab="Python" tab-group="language"
import json
import os

bank_range = json.load(open(os.environ["OPS_CONFIG"]))["profiles"]["security"]["bankRange"]
security.egress.allow_host("api.bank.test", "core banking")
security.egress.allow_range(bank_range, "core banking")
```

```ts tab="TypeScript"
import { readFileSync } from 'node:fs';

const bankRange = JSON.parse(readFileSync(process.env.OPS_CONFIG!, 'utf8')).profiles.security.bankRange;
await security.egress.allowHost('api.bank.test', 'core banking');
await security.egress.allowRange(bankRange, 'core banking');
```

```bash tab="CLI"
opsai egress --profile security allow-host api.bank.test --note 'core banking'
opsai egress --profile security allow-range "$(jq -r .profiles.security.bankRange "$OPS_CONFIG")" --note 'core banking'
```

Expected: both accepted. The saved sign-in names the private range the bank serves on.

### 2. Store the bank's two keys as secrets

```python tab="Python" tab-group="language"
builder.secrets.create("BANK_API_KEY", "dev-bank-key")
builder.secrets.create("STATEMENTS_API_KEY", "dev-bank-key")
```

```ts tab="TypeScript"
await builder.secrets.create('BANK_API_KEY', 'dev-bank-key');
await builder.secrets.create('STATEMENTS_API_KEY', 'dev-bank-key');
```

```bash tab="CLI"
printf %s dev-bank-key | opsai secrets create BANK_API_KEY
printf %s dev-bank-key | opsai secrets create STATEMENTS_API_KEY
```

Expected: 201 each; no response shows the value.

### 3. Import the OpenAPI document, tick place_hold, untick get_statement, save the draft

```python tab="Python" tab-group="language"
module = builder.tools.create_module("core_banking", "Core banking")
builder.tools.import_openapi(module["id"], "https://api.bank.test/openapi.json", ["get_account", "place_hold"])
```

```ts tab="TypeScript"
const module = await builder.tools.createModule('core_banking', 'Core banking');
await builder.tools.importOpenapi(module.id, 'https://api.bank.test/openapi.json', ['get_account', 'place_hold']);
```

```bash tab="CLI"
MODULE=$(opsai tools --json create core_banking --display-name "Core banking" | jq -r .id)
opsai tools import "$MODULE" https://api.bank.test/openapi.json --operation get_account --operation place_hold
```

Expected: reads are Read, `place_hold` is Write.

### 4. Request a security review; the Security approver publishes the module

```python tab="Python" tab-group="language"
asked = builder.tools.request_review(module["id"], "bank reads and one hold")
security.tools.decide_review(builder.tools.review_of(asked), "approved")
```

```ts tab="TypeScript"
const asked = await builder.tools.requestReview(module.id, 'bank reads and one hold');
await security.tools.decideReview(builder.tools.reviewOf(asked), 'approved');
```

```bash tab="CLI"
REVIEW=$(opsai tools --json request-review "$MODULE" --note "bank reads and one hold" | jq -r '.versions[] | select(.status == "in_review") | .reviewId')
opsai tools --profile security decide-review "$REVIEW" --decision approved
```

Expected: the module is published.

### 5. Import get_statement and publish a second version

```python tab="Python" tab-group="language"
builder.tools.import_openapi(module["id"], "https://api.bank.test/openapi.json", ["get_statement"])
made = builder.tools.publish_version(module["id"], "statements")
security.tools.decide_review(builder.tools.review_of(made), "approved")
```

```ts tab="TypeScript"
await builder.tools.importOpenapi(module.id, 'https://api.bank.test/openapi.json', ['get_statement']);
const made = await builder.tools.publishVersion(module.id, 'statements');
await security.tools.decideReview(builder.tools.reviewOf(made), 'approved');
```

```bash tab="CLI"
opsai tools import "$MODULE" https://api.bank.test/openapi.json --operation get_statement
REVIEW=$(opsai tools --json publish "$MODULE" --note statements | jq -r '.versions[] | select(.status == "in_review") | .reviewId')
opsai tools --profile security decide-review "$REVIEW" --decision approved
```

Expected: the version is listed; `get_statement` has no `api_key` input.

### 6. Run get_account and get_statement from the test panel

```python tab="Python" tab-group="language"
for tool, args in (("get_account", {"account_id": "CHQ-2219"}), ("get_statement", {"account_id": "CHQ-2219"})):
    builder.tools.run_module(module["id"], tool, args, real=True)
```

```ts tab="TypeScript"
for (const [tool, args] of [['get_account', { account_id: 'CHQ-2219' }], ['get_statement', { account_id: 'CHQ-2219' }]] as const) {
  await builder.tools.runModule(module.id, tool, args, { real: true });
}
```

```bash tab="CLI"
opsai tools run --module --real "$MODULE" get_account --input account_id=CHQ-2219
opsai tools run --module --real "$MODULE" get_statement --input account_id=CHQ-2219
```

Expected: both reach the bank.

### 7. Grant the three tools to Branch Concierge and publish it

```python tab="Python" tab-group="language"
# A write waits for a person only while the team asks before an agent changes anything.
security.with_team("team_ops").policies.set("toolWritesNeedApproval", True)
agent = next(a for a in builder.agents.list() if a["name"] == "Branch Concierge")
wanted = ["get_account", "get_statement", "place_hold"]
offered = {o["id"] for o in builder.agents.tool_options("Core banking")}
assert offered >= set(wanted), offered
builder.agents.grant_tools(agent["id"], wanted)
assert builder.agents.publish(agent["id"])["status"] == "approved"
```

```ts tab="TypeScript"
// A write waits for a person only while the team asks before an agent changes anything.
await security.withTeam('team_ops').policies.set('toolWritesNeedApproval', true);
const found = await Array.fromAsync(builder.agents.list());
const agent = found.find((a: { name: string }) => a.name === 'Branch Concierge');
const wanted = ['get_account', 'get_statement', 'place_hold'];
const offered = new Set((await builder.agents.toolOptions('Core banking')).map((o: { id: string }) => o.id));
assert.ok(wanted.every((id) => offered.has(id)));
await builder.agents.grantTools(agent.id, wanted);
assert.equal((await builder.agents.publish(agent.id)).status, 'approved');
```

```bash tab="CLI"
opsai policies set toolWritesNeedApproval true --profile security --team team_ops
AGENT=$(opsai agents --json list | jq -r '.[] | select(.name == "Branch Concierge") | .id')
opsai agents grant-tools "$AGENT" get_account get_statement place_hold
opsai agents --json publish "$AGENT" | jq -e '.status == "approved"'
```

Expected: the agent holds all three.

### 8. Ask the agent for an account

```python tab="Python" tab-group="language"
chat = builder.chat.start(agent["id"])["id"]
list(builder.chat.say(chat, 'call get_account {"account_id": "CHQ-2219"}'))
reply = [m for m in builder.chat.get(chat)["messages"] if m["role"] == "assistant"][-1]
assert reply["content"] == "Here is what I found.", reply
assert [call["name"] for call in reply["toolCalls"]] == ["get_account"], reply
```

```ts tab="TypeScript"
const chat = (await builder.chat.start(agent.id)).id;
await builder.chat.say(chat, 'call get_account {"account_id": "CHQ-2219"}');
const answered = (await builder.chat.get(chat)).messages.filter((m: { role: string }) => m.role === 'assistant').at(-1);
assert.equal(answered.content, 'Here is what I found.');
assert.deepEqual(answered.toolCalls.map((call: { name: string }) => call.name), ['get_account']);
```

```bash tab="CLI"
opsai chat say --agent "$AGENT" -m 'call get_account {"account_id": "CHQ-2219"}'
CHAT=$(opsai chat --json threads | jq -r '.[0].id')
opsai chat --json show "$CHAT" | jq -e '[.messages[] | select(.role == "assistant")] | last | .content == "Here is what I found." and ([.toolCalls[].name] == ["get_account"])'
```

Expected: "Here is what I found."; one call by the agent in the log.

### 9. Ask for a write: it is held

```python tab="Python" tab-group="language"
list(builder.chat.say(chat, 'call place_hold {"account_id": "CHQ-2219", "amount": 25, "reason": "suspected fraud"}'))
held = [m for m in builder.chat.get(chat)["messages"] if m["role"] == "assistant"][-1]
assert any(w["state"] == "pending" for w in held["widgets"]), held
```

```ts tab="TypeScript"
await builder.chat.say(chat, 'call place_hold {"account_id": "CHQ-2219", "amount": 25, "reason": "suspected fraud"}');
const held = (await builder.chat.get(chat)).messages.filter((m: { role: string }) => m.role === 'assistant').at(-1);
assert.ok(held.widgets.some((w: { state: string }) => w.state === 'pending'));
```

```bash tab="CLI"
opsai chat say --thread "$CHAT" -m 'call place_hold {"account_id": "CHQ-2219", "amount": 25, "reason": "suspected fraud"}'
opsai chat --json show "$CHAT" | jq -e '[.messages[] | select(.role == "assistant")] | last | .widgets | any(.state == "pending")'
```

Expected: an approval card; no call logged and no new hold at the bank.

### 10. The approver approves it

```python tab="Python" tab-group="language"
approver.tasks.approve(chat, password="northfield-demo")
```

```ts tab="TypeScript"
await approver.tasks.approve(chat, { password: 'northfield-demo' });
```

```bash tab="CLI"
echo northfield-demo | opsai tasks --profile approver approve "$CHAT" --password-stdin
```

Expected: one call runs and the bank holds exactly one new hold of 25.

### 11. The call log names the write

```python tab="Python" tab-group="language"
calls = approver.usage.list(tool="place_hold")
assert len(calls) == 1 and calls[0]["outcome"] == "ok", calls
```

```ts tab="TypeScript"
const calls = await approver.usage.list({ tool: 'place_hold' });
assert.equal(calls.length, 1);
assert.equal(calls[0].outcome, 'ok', JSON.stringify(calls));
```

```bash tab="CLI"
opsai tools --profile approver --json calls --tool place_hold | jq -e 'length == 1 and .[0].outcome == "ok"'
```

Expected: one row naming the agent, the approver and the outcome.

### 12. No key on any page

```python tab="Python" tab-group="language"
assert "dev-bank-key" not in json.dumps(builder.secrets.list())
```

```ts tab="TypeScript"
assert.ok(!JSON.stringify(await builder.secrets.list()).includes('dev-bank-key'));
```

```bash tab="CLI"
opsai secrets --json list | jq -e 'tostring | contains("dev-bank-key") | not'
```

Expected: no secret's listing carries its value. The console script checks the pages.

## Gaps

A row here is a product change tracked on the board; no test helper stands in for it, and the page does not pass while one is open. 

No gaps are open.

## What proves it

> [!IMPORTANT]
> Step 6's statement call answers 401 from the bank unless `{{STATEMENTS_API_KEY}}` in the query is resolved, and its
> `requestedUrl` carries the key unless the gateway scrubs it. Step 10 counts holds at the bank itself, so a write that
> ran twice or not at all fails it.

## In the console


`OPS_USECASE_MEDIA=1 make usecase-test UC=uc-086 LAYER=ui` writes the pictures and the clip beside this page (`media/`); the
script checks that the clip is under 15 s and 2 MB.

![The agents list, 1440 wide](media/uc-086-agents-1440.png)
![The agents list, 390 wide](media/uc-086-agents-390.png)
![The agent list, the agent holding its three tools and the module's call log](media/uc-086-agent-with-three-tools.gif)


### Steps and results in the console

| # | Step | Expected |
|---|---|---|
| 1 | Sam (Security admin) allows the bank's host and range | 201 |
| 2 | James adds `BANK_API_KEY` and `STATEMENTS_API_KEY` in Settings > Secrets, as Operations' secrets: a secret belongs to the team that uses it | 201 each; no response or page shows the value |
| 3 | James imports `https://api.bank.test/openapi.json`, ticks `place_hold`, unticks `get_statement`, saves the draft | 201; reads are Read, `place_hold` is Write |
| 4 | James requests a security review; Nadia approves it on the module's Approval tab | the module is published |
| 5 | James imports `get_statement` into the module and publishes a version | the version is listed on the Versions tab; `get_statement` has no `api_key` input |
| 6 | James runs `get_account` and `get_statement` from the test panel against the test environment | both reach the bank (a missing or wrong key answers 401); the URL the statement route repeats shows `api_key=[secret]` |
| 7 | James grants `get_account`, `get_statement` and `place_hold` to Branch Concierge and publishes it | the agent holds the three |
| 8 | James asks `call get_account {"account_id": "CHQ-2219"}` | "Here is what I found."; one call by the agent in the log |
| 9 | James asks `call place_hold {...25...}` | an approval card; no call logged and no new hold at the bank |
| 10 | Maya approves it in Reviews | one call runs and the bank holds exactly one new hold of 25 |
| 11 | James opens the module's Activity tab | the write's row names the agent that made it, Maya (by her sign-in email) as approver and the outcome, and links to the chat thread. The person who asked is not shown yet: the caller is the agents service until the runner signs a run context naming the user (planned, data-and-ai-gateways 4.3) |
| 12 | Every page | no page error, and the key never appears |

## Details

| | |
|---|---|
| Services the run starts | platform, agents and tools services on the scripted model, with a core-banking fake |
| Console script | `docs/usecases/console/scripts/test-uc-086-ui.mjs` |

### Preconditions


| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Maya Okafor (approver) on Operations, Nadia Petrov (approver) on Security, Priya Shah (admin), Sam Adeyemi (admin on Security, the only one who changes egress); password `northfield-demo` |
| The core-banking fake on https | the ui harness's `tools: { bank: 'core' }` (`services/tools-service/scripts/fake_bank`): an `X-Api-Key` header on most routes, an `api_key` query key on `get_statement`, holds that later reads return; key `dev-bank-key` |
| Agents granted from tools-service | the ui harness's `tools: { gateway: true }` |
| No model calls | the scripted model; a chat message `call <tool> <json>` calls that tool |
