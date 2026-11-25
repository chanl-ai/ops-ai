# A builder asks two versions of an agent one question and reads the replies side by side

Status: draft. Id: `uc-765`. Service: `console`. Layers: ui.

An agent's Versions tab links to Compare. Compare sends one question to the newest draft and to one saved version, each
on its own test thread, and draws the two replies next to each other, each labelled with its version. Nothing is
counted or remembered, as in Test.

## Preconditions

| Needs | How |
|---|---|
| A stack with platform sign-in and the scripted model | the ui harness with `platform: true` |
| An agent with two versions | James creates and publishes it (v1), then edits its instructions (v2, the draft) through the SDK |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Compare by its address, as from a bookmark or a reload | The picker reads "v1 (published)" and the composer asks "Ask v2 and v1…". **Open: red today.** The picker is blank and the composer reads "Ask v2 and v?…", because `TestCompare` takes its first choice from the versions list on its first render, before the list has loaded (`apps/console/src/components/agents/test-compare.tsx`, the `against` state) |
| 2 | He opens Versions and presses Compare | The picker reads "v1 (published)" and the page says "Ask both versions"; one question draws two sides, "v2 (newest)" and "v1", each with the question and a reply |
| 3 | The test threads James's page created are read back | One thread names no version (the newest) and one names v1 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `scripts/test-uc-765-ui.mjs` | draft |

## Non-vacuous check

Step 3: with `testVersion` left off the second thread, both sides run on the newest version and the versions read
back as `[2, 2]`.
