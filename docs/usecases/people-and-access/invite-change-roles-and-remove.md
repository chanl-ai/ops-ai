# Invite people and change their roles

Status: draft for review.

In this example we will have a clinic group's operations admin invite a scheduler and a billing clerk, change what the scheduler may do, and remove them, checking that a removed person's sign-in stops working at once and the team always keeps an admin. It assumes a signed-in admin who is the team's only admin.

| Use case | |
|---|---|
| Id | `uc-023` |
| Area | People and access |
| Runs | Python, TypeScript, CLI; console steps in their own script |
| Run it | `make usecase-test UC=uc-023` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| The clinic group's operations admin, the team's only admin | Admin | the `admin` profile |
| A scheduler and a billing clerk | Invited | an invite link each |

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI
from ops_ai.errors import Unauthorized

admin = OpsAI(profile="admin")
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const admin = new OpsAI({ profile: 'admin' });
```

```bash tab="CLI"
set -euo pipefail
export OPS_PROFILE=admin
```

## Steps

### 1. Invite two people as viewers

```python tab="Python" tab-group="language"
invited = admin.people.invite(["sched@clinic.example", "billing@clinic.example"], role="viewer")
links = {invite["email"]: invite["token"] for invite in invited["invites"]}
assert len(links) == 2
```

```ts tab="TypeScript"
const invited = await admin.people.invite(['sched@clinic.example', 'billing@clinic.example'], { role: 'viewer' });
const links = Object.fromEntries(invited.invites.map((i: { email: string; token: string }) => [i.email, i.token]));
assert.equal(Object.keys(links).length, 2);
```

```bash tab="CLI"
opsai people --json invite sched@clinic.example billing@clinic.example --role viewer > invited.json
jq -e '.invites | length == 2' invited.json
```

Expected: two invitations, one link each. No email is sent unless asked for.

### 2. The admin cannot step down while nobody else is an admin

```python tab="Python" tab-group="language"
me = admin.me.get()
changed = admin.people.change_role([me["memberId"]], "builder")
assert changed["skipped"][0]["reason"] == "last_admin"
```

```ts tab="TypeScript"
const me = await admin.me.get();
const changed = await admin.people.changeRole([me.memberId], 'builder');
assert.equal(changed.skipped[0].reason, 'last_admin');
```

```bash tab="CLI"
ME=$(opsai people --json me | jq -r .memberId)
opsai people --json role-change "$ME" builder | jq -e '.skipped[0].reason == "last_admin"'
```

Expected: skipped with `last_admin`; the admin is still an admin.

### 3. The scheduler accepts and is signed in to the team

```python tab="Python" tab-group="language"
scheduler = OpsAI.accept_invite(links["sched@clinic.example"], name="Sam Rivera")
assert scheduler.me.get()["teams"]["team_ops"] == "viewer"
```

```ts tab="TypeScript"
const scheduler = await OpsAI.acceptInvite(links['sched@clinic.example'], { name: 'Sam Rivera' });
assert.equal((await scheduler.me.get()).teams.team_ops, 'viewer');
```

```bash tab="CLI"
TOKEN=$(jq -r '.invites[] | select(.email == "sched@clinic.example") | .token' invited.json)
opsai login --invite "$TOKEN" --name "Sam Rivera" --profile scheduler
opsai people --profile scheduler --json me | jq -e '.teams.team_ops == "viewer"'
```

Expected: a session that already carries the team, as a viewer. No password is asked.

### 4. The admin makes the scheduler an approver

```python tab="Python" tab-group="language"
member = next(m for m in admin.people.list() if m["email"] == "sched@clinic.example")
admin.people.change_role([member["id"]], "approver")
assert next(m for m in admin.people.list() if m["id"] == member["id"])["role"] == "approver"
```

```ts tab="TypeScript"
const members = await admin.people.list();
const member = members.find((m: { email: string }) => m.email === 'sched@clinic.example');
await admin.people.changeRole([member.id], 'approver');
assert.equal((await admin.people.list()).find((m: { id: string }) => m.id === member.id).role, 'approver');
```

```bash tab="CLI"
MEMBER=$(opsai people --json list | jq -r '.[] | select(.email == "sched@clinic.example") | .id')
opsai people --json role-change "$MEMBER" approver > /dev/null
opsai people --json list | jq -e --arg id "$MEMBER" '.[] | select(.id == $id) | .role == "approver"'
```

Expected: the member list shows the new role.

### 5. A removed person's next call is refused

```python tab="Python" tab-group="language"
admin.people.remove([member["id"]])
try:
    scheduler.me.get()
    raise AssertionError("a removed member could still read /v1/me")
except Unauthorized:
    pass
```

```ts tab="TypeScript"
await admin.people.remove([member.id]);
await assert.rejects(scheduler.me.get(), { status: 401 });
```

```bash tab="CLI"
opsai people remove "$MEMBER"
if opsai people --profile scheduler me 2>/dev/null; then exit 1; fi
```

Expected: 401 at once; the removed person's API keys are refused the same way.

## Gaps

This page does not pass while a row here is open. Each open gap is a product change tracked on its own; no test helper stands in for it.

| Product fix | Step | Tab | What is missing | Where |
|---|---|---|---|---|
| The TypeScript SDK reads the saved profile | All | TypeScript | `new OpsAI({ profile })` cannot read the saved sign-in profile | `sdk/typescript/src/client.ts:257-263` |
| People verbs in both SDKs and the CLI | 1, 4, 5 | Python, TypeScript | `people.invite`, `people.list`, `people.remove` | `sdk/python/src/ops_ai/_words.py:262-266`, `sdk/typescript/src/words.ts:200-205` |
| People verbs in both SDKs and the CLI | 2, 4 | Python, TypeScript | `me.get`, `people.change_role` | as above |
| People verbs in both SDKs and the CLI | 3 | Python, TypeScript | `OpsAI.accept_invite` | as above |
| People verbs in both SDKs and the CLI | 2, 4 | CLI | `opsai people role-change` | `sdk/python/src/ops_ai/_cli/people.py:21-30` |
| People verbs in both SDKs and the CLI | 3 | CLI | `opsai login --invite` | `sdk/python/src/ops_ai/_cli/login.py` |
| People verbs in both SDKs and the CLI | 5 | CLI | `opsai people remove` | `sdk/python/src/ops_ai/_cli/people.py:21-30` |

## What proves it

> [!IMPORTANT]
> Step 5 fails if removal only hides the member from the list: the scheduler's session then still reads `/v1/me` and
> the check raises. Step 3 shows the same session working before the removal.

## In the console

| # | Step | Expected |
|---|---|---|
| 1 | Settings, Access | The team's members with their roles |
| 2 | Invite a new address as viewer | One form, says no email is sent, shows the link once |
| 3 | The link in a fresh browser | Names the team and the role; joins without a password |
| 4 | A builder opens Access | No Invite button |

## Details

| | |
|---|---|
| Services the run starts | platform service with its dev seed; no model is called |
| Console script | `docs/usecases/people-and-access/scripts/test-uc-023-ui.mjs`, moved here from `platform-service` when this page converts |
| Replaces | `test-uc-023-api.py`, deleted when this page passes |
