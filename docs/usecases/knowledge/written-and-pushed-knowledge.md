# Pages people write and items another system pushes become cited knowledge

Status: draft for review. A claims team at an insurer keeps its handbook in a knowledge base. People write pages in it,
the policy system pushes its product sheets into it, and every search names the page and version a passage came from.

| Use case | |
|---|---|
| Id | `uc-676` |
| Area | Knowledge |
| Runs | Python, TypeScript, CLI; console steps in their own script |
| Run it | `make usecase-test UC=uc-676` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| The claims knowledge owner | Builder | the `builder` profile |

The run gives each person a profile on a stack it starts for itself, so the code below is the code you run against
your own deployment once your profile points at it.

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI
from ops_ai.errors import BadRequest
import pytest

ops = OpsAI(profile="builder")
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ profile: 'builder' });
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=builder
```

## Steps

### 1. Create a knowledge base

The knowledge owner makes an empty base for the handbook.

```python tab="Python" tab-group="language"
handbook = ops.knowledge.create({"name": "Claims handbook"})
assert handbook["name"] == "Claims handbook"
```

```ts tab="TypeScript"
const handbook = await ops.knowledge.create({ name: 'Claims handbook' });
assert.equal(handbook.name, 'Claims handbook');
```

```bash tab="CLI"
HANDBOOK=$(opsai kb --json create "Claims handbook" | jq -r .id)
```

Expected: a knowledge base with no sources and no pages.

### 2. Write a page and find it by meaning

The owner writes the water damage rule as a page. A search that does not use the page's words still finds it.

```python tab="Python" tab-group="language"
page = ops.knowledge.add_page(handbook["id"], title="Water damage", text="Report a burst pipe within 14 days.")
assert page["outcome"] == "created"

found = ops.knowledge.search({"kbIds": [handbook["id"]], "question": "How long do I have to claim for a leak?"})
assert found["passages"][0]["title"] == "Water damage"
assert found["passages"][0]["version"] == 1
```

```ts tab="TypeScript"
const page = await ops.knowledge.addPage(handbook.id, { title: 'Water damage', text: 'Report a burst pipe within 14 days.' });
assert.equal(page.outcome, 'created');

const found = await ops.knowledge.search({ kbIds: [handbook.id], question: 'How long do I have to claim for a leak?' });
assert.equal(found.passages[0].title, 'Water damage');
assert.equal(found.passages[0].version, 1);
```

```bash tab="CLI"
opsai kb --json add-text "$HANDBOOK" --title "Water damage" --text "Report a burst pipe within 14 days." \
  | jq -e '.outcome == "created"'
opsai kb --json search "$HANDBOOK" "How long do I have to claim for a leak?" \
  | jq -e '.passages[0].title == "Water damage" and .passages[0].version == 1'
```

Expected: the page is created and indexed at once; the first passage is the page, at version 1.

### 3. The policy system pushes the same item twice

A push source takes items by name. Sending an item it already holds changes nothing, so the other system can resend
on every run without making duplicates.

```python tab="Python" tab-group="language"
feed = ops.knowledge.add_source({"type": "push", "name": "Policy system", "kbIds": [handbook["id"]]})
sheet = {"name": "home-cover.md", "text": "Home cover pays for sudden leaks, not gradual seepage."}

assert ops.knowledge.push(feed["id"], sheet)["outcome"] == "created"
assert ops.knowledge.push(feed["id"], sheet)["outcome"] == "unchanged"
```

```ts tab="TypeScript"
const feed = await ops.knowledge.addSource({ type: 'push', name: 'Policy system', kbIds: [handbook.id] });
const sheet = { name: 'home-cover.md', text: 'Home cover pays for sudden leaks, not gradual seepage.' };

assert.equal((await ops.knowledge.push(feed.id, sheet)).outcome, 'created');
assert.equal((await ops.knowledge.push(feed.id, sheet)).outcome, 'unchanged');
```

```bash tab="CLI"
FEED=$(opsai kb --json add-source "$HANDBOOK" --type push --name "Policy system" | jq -r .id)
echo "Home cover pays for sudden leaks, not gradual seepage." > home-cover.md

opsai kb --json push "$FEED" home-cover.md | jq -e '.outcome == "created"'
opsai kb --json push "$FEED" home-cover.md | jq -e '.outcome == "unchanged"'
```

Expected: `created`, then `unchanged`; no second sync runs.

### 4. New content under the same name is the next version

```python tab="Python" tab-group="language"
sheet["text"] = "Home cover pays for sudden leaks and for tracing the leak."
assert ops.knowledge.push(feed["id"], sheet)["outcome"] == "updated"

found = ops.knowledge.search({"kbIds": [handbook["id"]], "question": "Does home cover pay to trace a leak?"})
assert "tracing the leak" in found["passages"][0]["text"]
assert found["passages"][0]["version"] == 2
```

```ts tab="TypeScript"
sheet.text = 'Home cover pays for sudden leaks and for tracing the leak.';
assert.equal((await ops.knowledge.push(feed.id, sheet)).outcome, 'updated');

const again = await ops.knowledge.search({ kbIds: [handbook.id], question: 'Does home cover pay to trace a leak?' });
assert.match(again.passages[0].text, /tracing the leak/);
assert.equal(again.passages[0].version, 2);
```

```bash tab="CLI"
echo "Home cover pays for sudden leaks and for tracing the leak." > home-cover.md
opsai kb --json push "$FEED" home-cover.md | jq -e '.outcome == "updated"'
opsai kb --json search "$HANDBOOK" "Does home cover pay to trace a leak?" \
  | jq -e '(.passages[0].text | contains("tracing the leak")) and .passages[0].version == 2'
```

Expected: `updated`; the passage quotes the new text, at version 2, and the old text is no longer returned.

### 5. A source fed from Files refuses a pushed item

A file source is filled by uploads, so a pushed item is refused instead of mixing two ways in.

```python tab="Python" tab-group="language"
uploads = ops.knowledge.add_source({"type": "file", "name": "Uploads", "kbIds": [handbook["id"]]})

with pytest.raises(BadRequest) as refused:
    ops.knowledge.push(uploads["id"], {"name": "stray.md", "text": "Should not land."})
assert refused.value.code == "source_not_written"
```

```ts tab="TypeScript"
const uploads = await ops.knowledge.addSource({ type: 'file', name: 'Uploads', kbIds: [handbook.id] });

await assert.rejects(ops.knowledge.push(uploads.id, { name: 'stray.md', text: 'Should not land.' }), {
  code: 'source_not_written',
});
```

```bash tab="CLI"
UPLOADS=$(opsai kb --json add-source "$HANDBOOK" --type file --name Uploads | jq -r .id)
echo "Should not land." > stray.md

if refused=$(opsai kb push "$UPLOADS" stray.md 2>&1); then exit 1; fi
grep -q '^source_not_written:' <<<"$refused"
```

Expected: refused with `source_not_written`; the base still holds two items.

## What proves it

> [!IMPORTANT]
> Step 3 fails if pushing an item the base already holds starts a sync: the second push answers `updated` and the
> run count moves. It was seen failing that way with the unchanged check removed from the route.

## In the console

The console steps run in their own script, since a browser cannot run the code above.

| # | Step | Expected |
|---|---|---|
| 1 | Knowledge, Claims handbook, Add source, Typed text | Step 2 shows a title and a text field; Review shows no schedule |
| 2 | Create and sync | The item is indexed |
| 3 | Search the base for the typed text | The passage holds it |

## Details

| | |
|---|---|
| Services the run starts | knowledge, files and documents services; no model is called (search uses the scripted embedding) |
| Console script | `docs/usecases/kb-service/scripts/test-uc-676-ui.mjs` |
| Replaces | `test-uc-676-api.py` and `test-uc-676-sdk.py`, deleted when this page passes |
