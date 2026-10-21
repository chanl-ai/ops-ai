# The proposed settings tree is a mock a reviewer can walk

Status: current. Id: `uc-126`. Service: `console`. Layers: ui.

Card c-178: the settings standard is adopted, with a mock before any real page moves. `/preview/settings`
(development server only) draws the tree on sample data: My account, Team, Workspace, and Govern › Access, Policies,
Security and Models, each page built from one set of cards (`components/shared/setting/`). The live Settings pages and
their routes do not change. `docs/console/settings-tree.md` holds the S01 to S43 mapping and the dialog table.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | Sam Adeyemi (Security admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam opens every page of the tree | each loads with a header and no console error |
| 2 | He looks at the sidebar | the app sidebar is replaced by a back arrow, a Find box and My account at the bottom |
| 3 | He presses F, types "egress" and picks the result | the Find box has focus; Security opens |
| 4 | On the tool page he opens Add allowed host and Add secret and saves both, then goes to Security | the host is prefilled; both show on Security, where the same forms are cards |
| 5 | He switches the mock to a Builder | Security’s cards show a lock naming the Security admin and the fields are off |
| 6 | He opens Workspace › General | one card per setting, each with its own Save |
| 6b | He opens Govern › Policies | the seven policies of c-186 as cards of choices, each with its own Save; Publish review is off by default |
| 7 | He reads a field’s background in light and dark | lighter than the page both times |
| 8 | He opens API keys | the table starts with select-all and a middle-truncated, copyable id; Create key is in the header |
| 9 | At 420px wide he opens the agent page | eight tabs scroll sideways and the page does not widen |
| 10 | He drags the split handle on the agent page and reloads | the split moved and is kept |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-126-ui.mjs` | passing (13/13) |

## Non-vacuous check

Run with the workspace name field on `bg-background` and the tab list a plain `TabsList` (no scroll area), step 7 went red
(`light: field 250.43, page 250.43`) and step 9 went red (`scrolls: false`); both pass restored. Step 4 is the paired
success for the shared forms: a host added in the dialog has to appear in the card's list.
