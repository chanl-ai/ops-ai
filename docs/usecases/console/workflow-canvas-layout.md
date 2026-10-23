# Every workflow lays itself out cleanly on the canvas

Status: current. Id: `uc-486`. Service: `console`. Layers: ui.

Card c-486: one layout module places workflow steps (ELK, ports at their drawn heights), and lines are routed around
steps. The use case opens the demo workflows, the widest seed (`complaint_triage`) and fifty steps saved with no
positions in the step editor, and a run's canvas, which lay out through the same module. The design mock it was first
walked on (`/preview/workflow-layout`) was deleted in c-517; its checks run here on the real editor, except "Before",
which drew the seed as stored before the bake and has no real page.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson; password `northfield-demo` |
| The demo workflows | Saved by the script from `services/agents-service/seed/engine_workflows.json` and `scripts/demo/workflows/card_dispute_intake.json` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 8 | James opens `mail_intake`, `mail_document`, `levy_case`, `complaint_triage` (23 steps), `card_dispute_intake` and fifty steps in the editor at 1280 by 800 | fitted, or at zoom 0.65 or more with the trigger in the left third; no overlaps; no line through a step; every step drawn at its layout height within 2 px; no title or repeat line cut off; after Fit to view every step on screen |
| 9 | He opens a levy case saved by API with no positions | laid out on open; the same checks |
| 9b | On fifty steps he drags `step_10` 200 px down | its lines are clear of every step within 300 ms of the drop (measured 120 ms); no overlaps after; Fit to view is not checked, since fifty steps in a row are wider than the canvas at the least zoom |
| 10 | On `levy_case` he drags a step 200 px down and saves, presses T, then Cmd or Ctrl+Z | the drag saves as a new version; Tidy up moves the step; Undo puts it back where it was dragged |
| 11 | He presses T again and saves | the workflow is laid out exactly as the baked seed: version 1 again |
| 12 | He opens a run of the unplaced copy | laid out, no line through a step, no Tidy up, steps do not drag |
| 13 | At 400 px, light and dark, he presses Fit to view on `levy_case` | every step on screen |
| 14 | He opens a card dispute saved with steps 240 px apart, as staging stored workflows before steps grew to 288 px | laid out again on open, no overlaps; every workflow whose height fits opens centred top to bottom |
| 7 | Throughout | no page errors |

Script: `docs/usecases/console/scripts/test-uc-486-ui.mjs`. Screenshots and timings: `evidenceDir('486', 'editor')` and
`evidenceDir('486', 'timings')`. A position-only publish needing no review is held by
`services/agents-service/tests/api/test_publish_policy.py`: in a fresh stack the first publish of a workflow is a
major change and goes to review, so this use case does not reach it.
