# Connect an app with an API key

Status: draft for review.

In this example we will connect a logistics team's parcel carrier with an API key, track a parcel through it, rotate the key, and read the call log, checking that the key reaches the carrier and never comes back to a person or an agent. It assumes a signed-in builder and the carrier's address, which the run provides as a fake that repeats headers back, as a careless API might.

| Use case | |
|---|---|
| Id | `uc-013` |
| Area | Tools and apps |
| Runs | Python, TypeScript, CLI |
| Run it | `make usecase-test UC=uc-013` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| The operations builder who connects the carrier | Builder | the `builder` profile |

The carrier is a fake the run starts. It answers 401 without a key, returns a fingerprint of the key it received, and
repeats the request's headers in its answer, as a careless API might. Its address is in `CARRIER_URL`.

## Before you start

```python tab="Python" tab-group="language"
import json
import os
from ops_ai import OpsAI

ops = OpsAI(profile="builder")
CARRIER_URL = os.environ["CARRIER_URL"]
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI({ profile: 'builder' });
const CARRIER_URL = process.env.CARRIER_URL!;
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=builder
```

## Steps

### 1. Connect the carrier with its key

```python tab="Python" tab-group="language"
carrier = ops.apps.add_custom(
    "openapi", "Parcel carrier", base_address=CARRIER_URL, auth_kind="api_key", secrets={"apiKey": "ck_first_7Q2"}
)
assert "ck_first_7Q2" not in json.dumps(carrier)
```

```ts tab="TypeScript"
const carrier = await ops.apps.addCustom('openapi', 'Parcel carrier', {
  baseAddress: CARRIER_URL, authKind: 'api_key', secrets: { apiKey: 'ck_first_7Q2' },
});
assert.doesNotMatch(JSON.stringify(carrier), /ck_first_7Q2/);
```

```bash tab="CLI"
CARRIER=$(opsai apps --json add-custom openapi "Parcel carrier" --base-address "$CARRIER_URL" \
  --auth-kind api_key --secret apiKey=ck_first_7Q2 | tee carrier.json | jq -r .id)
! grep -q ck_first_7Q2 carrier.json
```

Expected: the app and its first account; the answer says a key is set and does not hold it.

### 2. Track a parcel through the carrier

```python tab="Python" tab-group="language"
tracked = ops.tools.run(carrier["id"], "track_parcel", {"parcel": "PX-40118"}, real=True)
assert tracked["output"]["keyFingerprint"] == "sha256:first"
assert tracked["output"]["echoedHeaders"]["X-Api-Key"] == "[secret]"
```

```ts tab="TypeScript"
const tracked = await ops.tools.run(carrier.id, 'track_parcel', { parcel: 'PX-40118' }, { real: true });
assert.equal(tracked.output.keyFingerprint, 'sha256:first');
assert.equal(tracked.output.echoedHeaders['X-Api-Key'], '[secret]');
```

```bash tab="CLI"
opsai tools --json run "$CARRIER" track_parcel --input parcel=PX-40118 --real \
  | jq -e '.output.keyFingerprint == "sha256:first" and .output.echoedHeaders["X-Api-Key"] == "[secret]"'
```

Expected: the carrier received the key; its echo of the header comes back as `[secret]`.

### 3. Rotate the key and call again

```python tab="Python" tab-group="language"
ops.accounts.set_key(carrier["id"], "ck_second_9M4")
tracked = ops.tools.run(carrier["id"], "track_parcel", {"parcel": "PX-40118"}, real=True)
assert tracked["output"]["keyFingerprint"] == "sha256:second"
```

```ts tab="TypeScript"
await ops.accounts.setKey(carrier.id, 'ck_second_9M4');
const again = await ops.tools.run(carrier.id, 'track_parcel', { parcel: 'PX-40118' }, { real: true });
assert.equal(again.output.keyFingerprint, 'sha256:second');
```

```bash tab="CLI"
opsai apps set-key "$CARRIER" ck_second_9M4
opsai tools --json run "$CARRIER" track_parcel --input parcel=PX-40118 --real \
  | jq -e '.output.keyFingerprint == "sha256:second"'
```

Expected: the next call carries the new key.

### 4. The call log holds neither key

```python tab="Python" tab-group="language"
calls = ops.usage.list(tool="track_parcel")
assert len(calls) == 2
assert "ck_first_7Q2" not in json.dumps(calls) and "ck_second_9M4" not in json.dumps(calls)
```

```ts tab="TypeScript"
const calls = await ops.usage.list({ tool: 'track_parcel' });
assert.equal(calls.length, 2);
assert.doesNotMatch(JSON.stringify(calls), /ck_first_7Q2|ck_second_9M4/);
```

```bash tab="CLI"
opsai tools --json calls --tool track_parcel > calls.json
jq -e 'length == 2' calls.json
! grep -qE 'ck_first_7Q2|ck_second_9M4' calls.json
```

Expected: two logged calls, each saying whom it ran as; neither key appears.

## Gaps

This page does not pass while a row here is open. Each open gap is a product change tracked on its own; no test helper stands in for it.

| Product fix | Step | Tab | What is missing | Where |
|---|---|---|---|---|
| The TypeScript SDK reads the saved profile | All | TypeScript | `new OpsAI({ profile })` cannot read the saved sign-in profile | `sdk/typescript/src/client.ts:257-263` |
| `opsai apps add-custom` and `set-key` | 1 | CLI | `opsai apps add-custom` | `sdk/python/src/ops_ai/_cli/apps.py:20-51` |
| `opsai apps add-custom` and `set-key` | 3 | CLI | `opsai apps set-key` | `sdk/python/src/ops_ai/_cli/apps.py:20-51` |

## What proves it

> [!IMPORTANT]
> Step 2 fails if the gateway stops scrubbing what a system sends back: the carrier's echoed header then carries the
> key, and the check on `[secret]` fails.

## Details

| | |
|---|---|
| Services the run starts | platform and tools services, and the fake carrier on a private address the account's egress list allows |
| Replaces | `docs/usecases/tools-service/scripts/test-uc-013-api.py`, deleted when this page passes |
