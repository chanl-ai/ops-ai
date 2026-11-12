# A builder checks, saves and test-runs a three-step workflow from a file

Status: draft for review. A software company's support team takes requests from its billing app and maps them onto
its own fields. The builder keeps the workflow in a file, checks it, saves it as a draft and test-runs it, and a
request with a missing field is refused with the field's name.

| Use case | |
|---|---|
| Id | `uc-623` |
| Area | Workflows |
| Runs | Python, TypeScript, CLI |
| Run it | `make usecase-test UC=uc-623` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| The support operations builder | Builder | the `builder` profile |

## The workflow file

The run writes this file next to the code before it starts. It is the same file as the example folder's
`resources/workflow.yaml`, cut to its three steps.

```yaml title="workflow.yaml"
schemaVersion: 2
id: normalize_support_request
name: Normalize a support request
nodes:
- id: start
  type: ops.trigger.request
  typeVersion: 1
  parameters:
    inputSchema:
      type: object
      required: [customerEmail, subject, message]
- id: map
  type: ops.data.set
  typeVersion: 1
  parameters:
    values:
      customer.email: $.input.customerEmail
      title: $.input.subject
      body: $.input.message
- id: done
  type: ops.flow.end
  typeVersion: 1
  parameters:
    outcome: accepted
connections:
- { from: { node: start, port: payload }, to: { node: map, port: in } }
- { from: { node: map, port: out }, to: { node: done, port: in } }
```

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI
from ops_ai.errors import BadRequest
import pytest

ops = OpsAI(profile="builder")
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ profile: 'builder' });
const definition = readFileSync('workflow.yaml', 'utf8');
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=builder
```

## Steps

### 1. Check the file

```python tab="Python" tab-group="language"
check = ops.workflows.validate("workflow.yaml")
assert check.ok, check.errors
```

```ts tab="TypeScript"
const check = await ops.workflows.validate(definition);
assert.ok(check.ok, JSON.stringify(check.errors));
```

```bash tab="CLI"
opsai workflows --json validate workflow.yaml | jq -e '.ok'
```

Expected: no errors.

### 2. Save it as a draft

```python tab="Python" tab-group="language"
saved = ops.workflows.apply("workflow.yaml")
assert saved["workflowId"] == "normalize_support_request"
```

```ts tab="TypeScript"
const saved = await ops.workflows.apply(definition);
assert.equal(saved.workflowId, 'normalize_support_request');
```

```bash tab="CLI"
opsai workflows --json apply workflow.yaml | jq -e '.workflowId == "normalize_support_request"'
```

Expected: the draft is stored under its id; running `apply` again with the same file changes nothing.

### 3. Test-run a request from the billing app

```python tab="Python" tab-group="language"
request = {"customerEmail": "ada@example.test", "subject": "Invoice 4471", "message": "I was charged twice."}
run = ops.workflows.run("normalize_support_request", input=request, mode="test", wait=True)
assert (run["status"], run["outcome"]) == ("succeeded", "accepted")
```

```ts tab="TypeScript"
const request = { customerEmail: 'ada@example.test', subject: 'Invoice 4471', message: 'I was charged twice.' };
const run = await ops.workflows.run('normalize_support_request', { input: request, mode: 'test', wait: true });
assert.deepEqual([run.status, run.outcome], ['succeeded', 'accepted']);
```

```bash tab="CLI"
echo '{"customerEmail": "ada@example.test", "subject": "Invoice 4471", "message": "I was charged twice."}' > request.json
opsai workflows --json run normalize_support_request --input request.json --test --wait \
  | jq -e '.status == "succeeded" and .outcome == "accepted"'
```

Expected: the run succeeds with the outcome `accepted`. A test run reaches no real system.

### 4. A request without an email is refused by name

```python tab="Python" tab-group="language"
with pytest.raises(BadRequest) as refused:
    ops.workflows.run("normalize_support_request", input={"subject": "Invoice 4471", "message": "?"}, mode="test")
assert refused.value.code == "invalid_input"
assert refused.value.details["path"] == "customerEmail"
```

```ts tab="TypeScript"
await assert.rejects(
  ops.workflows.run('normalize_support_request', { input: { subject: 'Invoice 4471', message: '?' }, mode: 'test' }),
  { code: 'invalid_input', details: { path: 'customerEmail' } },
);
```

```bash tab="CLI"
echo '{"subject": "Invoice 4471", "message": "?"}' > no-email.json
if refused=$(opsai workflows run normalize_support_request --input no-email.json --test 2>&1); then exit 1; fi
grep -q '^invalid_input: customerEmail:' <<<"$refused"
```

Expected: refused with `invalid_input` at `customerEmail`; no run starts.

## What proves it

> [!IMPORTANT]
> Step 4 fails if the request trigger stops checking its schema: the run starts and `pytest.raises` reports that
> nothing was raised. Step 3 alone could pass on a workflow that accepts anything.

## Details

| | |
|---|---|
| Services the run starts | platform and agents services and the workflow worker; no model is called |
| Example folder | `examples/workflows/01-normalize-a-request/` holds the same workflow for copying |
| Replaces | `docs/usecases/agents-service/scripts/test-uc-623-sdk.py` and `test-uc-623-cli.py`, deleted when this page passes |
