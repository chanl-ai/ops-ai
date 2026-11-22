# One create form holds a name to the same rule the server keeps

Status: draft. Id: `uc-768`. Service: `console`. Layers: ui.

A name field on a create form checks the name before sending, with the sentence the server would give: a name of 200
letters saves, one of 201 and a blank one stay in the dialog with a message and send nothing, and a name in Chinese
saves. The New guardrail dialog stands for every form that takes its name through `nameError`
(`apps/console/src/lib/validation/names.ts`).

## Preconditions

| Needs | How |
|---|---|
| A stack with platform sign-in | the ui harness with `platform: true`; James (builder) signs in |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens New guardrail and creates one named with 200 letters | 201; the guardrail is listed under that name |
| 2 | He creates one named with 201 letters | The dialog stays open and says "The name is at most 200 characters."; no request is sent |
| 3 | He submits a blank name | The dialog says "Name the guardrail."; no request is sent |
| 4 | He creates one named 客户风险守则 | 201; listed under those letters |
| 5 | A 201-letter name is posted straight to the route | Refused with a 4xx and a sentence that names 200 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `scripts/test-uc-768-ui.mjs` | draft |

## Non-vacuous check

Step 2: with the console's length check removed, the 201-letter name is sent and the dialog shows the server's
refusal after a request, so the "sends nothing" half fails.
