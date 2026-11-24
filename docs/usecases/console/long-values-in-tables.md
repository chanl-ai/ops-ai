# A long list or text in a table cell stays inside its column

Status: draft. Id: `uc-772`. Service: `console`. Layers: ui.

A table cell with many values shows the first few and "+N more"; a long text is cut to its column. Both open the full
value in a popover that a click, a tap or the keyboard reaches, and a click inside a clickable row's cell never opens
the row.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | the ui harness with `platform: true, demo: true` |
| A builder | James Richardson (`services/platform-service/seed/people.json`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open the document type `legal_notice` | Its currency field shows three values and "+N more"; choosing it opens a popover named "Allowed values" holding every value, and the table does not scroll sideways at 1440 or 390 |
| 2 | On a clickable row (Tool access, Guardrails or Access), choose "+N more" and then a value in its popover | The address stays the same; the row does not open |
| 3 | Open the model `mr_wf_wire` and read its findings and conditions | Each cut text is a button with the whole text in its title; choosing it opens a popover named "Full text" holding the whole text |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-772-ui.mjs` | draft |

## Non-vacuous check

Step 1: with the raw `join(', ')` back in the field's cell, there is no "+N more" and the table scrolls sideways. Step 2: without `StopRowClick` around the trigger, the click opens the row and the address changes.
