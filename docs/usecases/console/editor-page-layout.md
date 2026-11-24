# Record editors and list pages share one header, one tab strip and one section style

Status: draft. Id: `uc-781`. Service: `console`. Layers: ui.

The agent page, the workflow editor and every list page draw one title block (icon, title and description on one left
edge, one h1), one row for the save state and the actions, and one tab strip. Agent tabs use one section heading.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | the ui harness with `platform: true, demo: true` |
| A builder and a viewer | James Richardson and Rohan Menon in Operations (`services/platform-service/seed/people.json`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open the agents list, an agent, an agent that does not exist, a workflow editor, Connectors, Skills and the model inventory at 1440 and 390 | Each has one h1, no sideways page scroll, and a title and description on one left edge with the icon level with the title |
| 2 | Open the workflow editor | One tab strip: Canvas and Versions; the section's sibling pages are not a second strip |
| 3 | Open an agent as the builder | The save state sits beside Save and shares one row with the other actions (one row at 390); the last link of the breadcrumb is the agent's name |
| 3b | Open the workflow editor, live and paused, as the builder and as the viewer at 390 | The actions and the Version and Live chip wrap as one group: no action alone on its own row |
| 4 | At 390 scroll the agent's tab strip | Every tab can be scrolled into view |
| 5 | Walk the agent's Settings, Evals, Channels and Limits tabs | One section heading size; Limits fills the width; Run evals sits on the heading row; View prompt sits at the brief card's right edge |
| 6 | Choose a step on the canvas | The step sheet lies inside the console panel at 1440 and keeps the page margin at 390, with its close button level with its title |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-781-ui.mjs` | draft |

## Non-vacuous check

Step 2: with the section tabs drawn beside the page's own tabs (as before), two strips are found. Step 1: with the page
title a level-two heading, no h1 is found.
