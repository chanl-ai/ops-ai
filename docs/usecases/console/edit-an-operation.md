# A builder edits an operation's input, access and approval policy

Status: current. Id: `uc-090`. Service: `console`. Layers: ui.

c-073 in one run, signed in as the seeded people: a builder changes what an agent may send to an operation, its
access and its step-up, sees which secrets it reads, and every change is staged as major or minor by what it changes
for the agent. The design is [tool lifecycle](../../architecture/tool-lifecycle.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder) on Operations, Nadia Petrov (approver) and Sam Adeyemi (admin) on Security; password `northfield-demo` |
| A published module with a read and a write | set up through the API: Sam lists `rates.bank.test`, James creates the module with `get_rate` (header `X-Api-Key: {{RATES_KEY_…}}`) and `place_fx_hold`, Nadia approves its review |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Tools | the module's row says "1 secret not set", linking to Settings > Secrets |
| 2 | He opens `get_rate` | the Secrets section names the key as not set |
| 3 | He adds an integer field with the default "ten" and stages | 422; "the default must be of type integer" shows on that field |
| 4 | He makes it an optional string `tier` with allowed values `retail, wholesale`, no default, and stages | staged as a minor schema change; the allowed values reach tools-service (a default would be major: it is sent for the agent on reads) |
| 5 | He adds a required field `branch` and stages, then opens Publish version | staged as major ("branch added (required)"); the dialog asks "Publish a major version?" |
| 6 | He turns on the write's step-up, and makes the read a write | both staged; the read now waits for an approval; the access change is major |
| 7 | Sam sets the secret; James reopens the read and the list | the sheet says Set; the list no longer warns |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-090-ui.mjs` | passing |

## Non-vacuous check

Steps 3 to 6 read tools-service's answer to the console's PATCH, so a sheet that only redraws its own state fails
them; step 1 and 7 read the list tools-service serves.
