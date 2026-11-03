# A team reviews a plugin update before its tools change

Status: current on main behind the `plugin_updates` install flag (off by default) and `OPS_PLUGINS`, which the layer
turns on for its own services. Id: `uc-609`. Service: `tools-service` with platform-service and agents-service. Layers:
api, ui. Guide: `docs/guide/plugins.md`, Plugin updates.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | After the operator installs a newer plugin version, a team keeps calling its own version's tools exactly as declared: a changed tool keeps its request, a removed one still answers and stays listed, and a tool or value only the new version has is refused naming the update | api | 1-4 | 2 |
| S2 | The team's review lists each new, changed and removed tool with its input changes | api | 5 | 5 |
| S3 | The review can name the team's agents and workflows that use each changed or removed tool | api | 6 | 6 |
| S4 | A team admin takes the update: a stale review is refused, the team runs the new version from its next call, and another team keeps its version | api | 7-8 | 8 |
| S5 | On the app's page a team admin sees Update available, reviews each tool with who uses it and the version each template copy came from, and takes the update with one button | ui | 9-11 | 10 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins and the flag on | The layer starts tools-service with `OPS_PLUGINS=true` and `OPS_FLAGS=["plugin_updates"]` |
| Two versions of one plugin | `services/tools-service/tests/plugin_fields/fields_desk` (0.1.0), then `services/tools-service/tests/plugin_versions/fields_desk` (0.2.0) after a restart on the same database: find takes pending and moves, post_message moves, transfer is gone, close_case is new |
| A fake system | `docs/usecases/lib/fake_multi_auth.py`: records the path each call reached, takes chat messages only as a form and counts transfers |
| People | Sam Adeyemi (Security admin), Priya Shah (team_ops admin), Wanjiru Kamau (team_platform admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The platform admin turns the fields desk on; Priya and Wanjiru turn it on for their teams with its token | Each team's review reads 0.1.0 with nothing waiting |
| 2 | tools-service restarts with 0.2.0 installed; a run in team ops calls post_message, transfer and find (open) | The fake saw `/fields/chat.postMessage`, one transfer, and find at `/fields/search` |
| 3 | The run calls find with `pending`, and close_case | Both refused, close_case naming the update; the fake received nothing |
| 4 | Priya lists team ops' tools | `fields_transfer` is listed, `fields_close_case` is not |
| 5 | Priya reads the review | 0.1.0 to 0.2.0: find's status changed, post_message's request changed, transfer removed, close_case new |
| 6 | Priya grants a team ops agent post_message and transfer, then asks who uses them | The agent is named for both |
| 7 | Priya takes the update with a digest from no review, then with the review's | 409 `update_changed`; then the team runs 0.2.0 with nothing waiting |
| 8 | Runs in team ops call post_message, close_case and transfer; a run in team platform calls post_message | Team ops reaches `/fields/chat.post`, closes the case, and is refused transfer; team platform still reaches `/fields/chat.postMessage` |
| 9 | (ui) The stack runs 0.2.0; after Priya turns the desk on, her team's binding holds what 0.1.0 declares, the state step 2 leaves. She opens the desk's page | Update available: 1 new tool, 2 changed, 1 removed, naming 0.1.0 and 0.2.0 |
| 10 | She opens the review | Each tool with what changed (find changes status), "Used by Message desk (agent)" under post_message, and under Your copies, Desk helper made from version 2 (installed after the turn-on), at 1280 and 400 wide |
| 11 | She takes the update | The notice goes; the team runs 0.2.0 |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | The fake records the path each call reached, which differs between the versions; a call built from the installed manifest reaches the new path |
| 3 | The fake's call count is read before and after: a refusal that still sent fails the step |
| 7 | The stale digest is a well-formed one no version has, so only the digest check can refuse it |
| 8 | Team platform's call comes after team ops' take, so a take that changed the account's tools for everyone fails it |

## Results

| Layer | Script | Result |
|---|---|---|
| api | `tools-service/scripts/test-uc-609-api.py` | passing (2026-11-01), 8 checks |
| ui | `tools-service/scripts/test-uc-609-ui.mjs` | passing (2026-11-01), 6 checks |
