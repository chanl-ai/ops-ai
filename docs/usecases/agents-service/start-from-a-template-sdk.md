# Start a skill from a template

Status: current. Service: `agents-service`. Layers: sdk, cli.

In this example we will list the templates a team is offered, one kind at a time, install the starter skill "Doc
co-authoring" as the team's own copy and find it in the team's skills. It assumes the starters pack is on for the
team and Priya, the team's admin, is signed in.

| Use case | |
|---|---|
| Id | `uc-740` |
| Area | Agents |
| Runs | Python, TypeScript, CLI |
| Run it | `make usecase-test UC=uc-740` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| Priya, the team's admin | Admin | the `priya` profile |

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI

priya = OpsAI(profile="priya")
KINDS = ["agent", "skill", "workflow", "guardrail", "case_type", "task_type"]
REF = "plugin:opsai.starters:doc-coauthoring"
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const priya = new OpsAI({ profile: 'priya' });
const KINDS = ['agent', 'skill', 'workflow', 'guardrail', 'case_type', 'task_type'];
const REF = 'plugin:opsai.starters:doc-coauthoring';
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=priya
```

## Steps

### 1. List the templates of each kind

Each list holds only its kind. The skill list offers Doc co-authoring, and Priya may add it.

```python tab="Python" tab-group="language"
lists = {kind: priya.templates.list(kind=kind) for kind in KINDS}
for kind, rows in lists.items():
    assert all(t["kind"] == kind for t in rows), (kind, [t["id"] for t in rows])
starter = next(t for t in lists["skill"] if f"{t['source']}:{t['id']}" == REF)
assert starter["canAdd"]
```

```ts tab="TypeScript"
const lists = Object.fromEntries(await Promise.all(KINDS.map(async (kind) => [kind, await priya.templates.list({ kind })])));
for (const [kind, rows] of Object.entries(lists)) {
  assert.ok((rows as any[]).every((t) => t.kind === kind), `${kind} list holds another kind`);
}
const starter = (lists.skill as any[]).find((t) => `${t.source}:${t.id}` === REF);
assert.ok(starter?.canAdd);
```

```bash tab="CLI"
for kind in agent skill workflow guardrail case_type task_type; do
  opsai templates list --kind "$kind" --json | jq -e --arg k "$kind" 'all(.[]; .kind == $k)'
done
opsai templates list --kind skill --json | jq -e 'map(select(.source + ":" + .id == "plugin:opsai.starters:doc-coauthoring"))[0].canAdd'
```

Expected: six lists, each of one kind; Doc co-authoring is offered with `canAdd`.

### 2. Install the starter skill

The install makes the team's own copy, through the checks creating a skill by hand goes through.

```python tab="Python" tab-group="language"
made = priya.templates.install(REF)
assert made["created"] is True
record = made["copy"]["recordId"]
```

```ts tab="TypeScript"
const made = await priya.templates.install(REF);
assert.equal(made.created, true);
const record = made.copy.recordId;
```

```bash tab="CLI"
opsai templates install plugin:opsai.starters:doc-coauthoring --json | jq -e '.created == true and (.copy.recordId | length > 0)'
```

Expected: `created` is true and the copy has a record id.

### 3. Find it in the team's skills

```python tab="Python" tab-group="language"
skills = priya.raw.agents.agents_list_skills()
rows = skills["data"] if isinstance(skills, dict) else skills
assert record in [s["id"] for s in rows]
```

```ts tab="TypeScript"
const skills = (await priya.raw.agents.agents_list_skills({})) as any;
const rows = Array.isArray(skills) ? skills : skills.data;
assert.ok(rows.some((s: any) => s.id === record));
```

```bash tab="CLI"
opsai resources list plugin:opsai.starters --json | jq -e 'map(select(.id == "doc-coauthoring"))[0].copy != null'
```

Expected: the copy is in the team's skills.

## What proves it

Step 1 fails if a kind's list holds another kind, or the starter is not offered to an admin. Step 2 fails if the install
makes no copy. Step 3 fails if the copy exists but is not among the team's skills.

## Details

| | |
|---|---|
| Services the run starts | agents stack: platform-service, tools-service with the starters pack, agents-service |
| Pack | the starters pack is read from `ops-ai-plugins` beside this repo, or from `OPS_USECASE_STARTERS_PACK` |
