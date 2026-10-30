# A builder edits steps in a side sheet and adds them from a tabbed panel

Status: current. Id: `uc-122`. Service: `console`. Layers: ui.

an earlier change (split from an earlier change), owner feedback (mid-1): a step and the trigger open in a sheet beside the canvas that leaves
the canvas usable, and steps are added from a floating panel with a tab per group and a search across every group.

## Preconditions

| Needs | How |
|---|---|
| The demo stack | the ui harness with `demo: true`: platform sign-in as James; the script saves a ten-step draft through `POST /v1/workflows/definitions` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Press N, open the Tools tab, then search "review" and pick Human review | Tools lists only tool steps; the search finds Human review from another tab; the step is added and its sheet opens |
| 2 | Open Assess the wire, change its prompt, click Look up the customer, then Assess the wire again | No overlay; the sheet moves to each step clicked; the prompt edit is kept |
| 3 | Click the trigger | How it starts names `POST /v1/runs` and the workflow's tool name; Run input lists wire_id and customer_id as required |
| 4 | Clear the hold step's operation in its JSON | The message shows at the top of the sheet and under Operation |
| 5 | Press Escape | The sheet closes |
| 6 | Open the same workflow with its review set to expire after 4 hours, its timeout wired to Needs a person | The review step has a timeout port; the workflow that waits has none |
| 7 | Open a workflow whose switch has the cases large and known | The switch's ways out are large, known, then otherwise |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-122-ui.mjs` | passing |
