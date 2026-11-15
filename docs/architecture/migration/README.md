# Migration to the engineering standards

Status: current, 2026-11-15. The plan an agent executes to move every service, the console and the SDKs onto the
[engineering standards](../engineering-standards.md). The standards say what good looks like; this folder says the
order, the files, the commands and the proof. Where a page here and a standards page disagree, the standards page wins.

## The goal

Every rule under [standards/](../standards/) holds on `develop`, with a check that fails when it is broken, and the
product behaves as it does today. Rewrite the layers, keep the logic: each service's store and request layers are
replaced wholesale against eight shared components; domain logic, plugins and console screens stay as they are; the
console's data layer moves to screen-shaped reads in its own lane.

What this buys: one customer never sees another's rows and the database enforces it on every table (`TN1`, `TN2`);
each screen is one call in one transaction with its labels and counts in it (`DA1`, `DA5`, `UI1`); who may do what is
decided only by `can()` (`AC1`); a missing setting stops a service at start (`CF3`); every check runs on every change,
the same locally and in CI, on both databases (`DL2`, `TS6`).

## The phases

| Phase | Page | What lands | Builders | Size, builder days | Calendar, working days |
|---|---|---|---|---|---|
| 0 | [components.md](components.md) | The eight shared components in the kit and its packages, each with its check at today's count | up to 3, in three tracks | 16.5 to 20 | 6 to 7 before the pilot opens; C8 lands during the pilot |
| 1 | [pilot.md](pilot.md) | documents, files, models and runner on every component, in one pull request; the coverage gap measured and published | 1, or 2 split store and request | 4 to 6 | 3 to 5 |
| 2 | [lane-platform.md](lane-platform.md), [lane-kb.md](lane-kb.md), [lane-tools.md](lane-tools.md), [lane-agents.md](lane-agents.md) | Four lanes at once, one service each: its store and request layers replaced wholesale | 4, or 5 with agents split | 27 to 35 | 7 to 9 (agents with two builders; tools is then the longest) |
| 3 | [lane-console.md](lane-console.md) | The console's data layer onto the list contract and the fields the lanes return | 1 | 4 to 6 | starts with phase 2, closes 2 to 3 days after the agents lane merges |

Total: 51.5 to 67 builder days; 18 to 25 working days end to end, which is four to five weeks of calendar time. Three
weeks is not reachable: the serial path C1, C2, pilot, agents lane, console closing is 16 working days at the best end
of every range. The earlier plan that moved call sites one by one counted 38 to 48 builder days; the wholesale rewrite
costs about a third more builder time and saves calendar time because every lane runs at once and each file is edited
once. The least certain number is the agents lane (8,504 store lines in 43 files; 19,852 api lines in 91 files, most of
them domain logic that stays).

### How the sizes are counted

| Work | Rate assumed | Basis |
|---|---|---|
| Store layer rewritten onto the base with typed rows | 1,800 lines a builder day | Mechanical once the pilot has set the pattern: a class gains `Store`, `engine.begin()` becomes `self.tx()`, each function names its columns and returns a model through `rows()` |
| Request layer swapped | 70 route functions a builder day | A route gains `Tx`, `ListQuery`, an `In` body and an `Out` reply; the function it calls keeps its logic |
| A table marked and policed, with its backfill and down path | 0.1 day a table | One migration per service chain emits the policy DDL for both databases |
| Fixed items per lane | 1 to 2 days | Relay wiring, clients and endpoints, access lines from the register, the budgets file, loop tests |

The pilot publishes the measured rates for the four lanes to check their sizes against.

## What is replaced and what is kept

| Layer | Fate | Rule |
|---|---|---|
| `services/<x>/src/<pkg>/store/` | Replaced: every class extends `Store`, every function takes `conn` or calls `self.tx()`, every row leaves as an `Out` model | `LY3`, `TN2`, `DA1`, `MD4` |
| Route signatures, bodies, replies, paging, clients, relay wiring, settings fields | Replaced: `Tx`, `CurrentPrincipal`, `ListQuery`, `In`, `Out`, `ServiceClient.for_settings`, `relay()`, `Endpoint` | `AP1`, `MD1`, `DA5`, `CF2`, `EV2` |
| Domain logic the routes call: graph execution, extraction, gateway calls, OAuth, MCP, ingest, chunking | Kept, inputs retyped where a dict crossed a layer | `LY1`, `MD4` |
| `packages/ops_plugin_sdk`, `builtin-plugins/`, `plugins/` | Kept | |
| Console pages and components under `apps/console/src/app` and `components/` | Kept; hooks and `lib/api` move to the list contract in the console lane | `UI1`, `UI2` |
| `sdk/` | Regenerated once on `develop` after each merged lane, by one hand, never inside a lane's pull request | `UI6`, `MD2` |

The request layer is the plumbing a route owns: its signature and dependencies, its body and reply models, how it
pages, how it opens a transaction, how it reaches another service. In agents-service and platform-service that
plumbing sits in `api/` beside domain functions; the plumbing is replaced and the domain functions are kept and
retyped. In the small services it is `app.py` and the client modules.

## The rules every lane follows

| Rule | Detail |
|---|---|
| Freeze | Until phase 3 merges, no pull request into `develop` touches `services/`, `packages/` or `apps/console/` unless it is a component, the pilot or a lane. A production fix lands on `develop` first and every open lane rebases on it the same day |
| One branch, one pull request | Every component and every service lands on the single branch `refactor/services-onto-shared-components`, in one pull request, in this order: the components, the small services, platform, kb, tools, agents, console. Each step is its own commits, by path |
| Tests first, per failure mode | Before a lane rewrites, it lists the routes and store functions a use case or test does not reach and writes one api-layer test per uncovered route a screen uses (`TS1`, `TS3`); the pilot page gives the method |
| Baselines shrink in the lane | Each check has a file per service (`portable-baseline.txt` today; the raw-site, savepoint, config-literal and typed-boundary lists the components add). A lane takes its own file to zero and edits no other lane's file |
| No new breach anywhere | Each component's check is red on a new site from the day it merges, so the freeze is enforced by the gate, not by asking |
| Access decisions | Every site on `access-exceptions-allowlist.txt` is converted onto `can()` or `policy()`, kept with its register reason, or deleted with its code, as the register says (`AC1`, `AC2`) |
| Hard git rules | Commit subject at most 72 characters, body at most 3 lines; no `--no-verify`, no stash, no force push, never push `main` or `develop` directly |
| Public repository | No tracker ids, no private paths, no customer names in code, commits or docs |

## How to verify

| Check | Command | When |
|---|---|---|
| One service's tests on a throwaway database | `make -s test PKG=services/<x>` | Every commit in a lane |
| Only the tests a change touches | `make test-impacted BASE=origin/develop` | Before a push |
| The lane's use cases, in parallel | `make usecase-batch UCS="uc-013:api uc-607"` with the service's ids from `make usecase-coverage SERVICE=<x>-service` | Before the pull request opens and after each rebase |
| The use cases a change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` | Before the pull request opens |
| Everything a commit must pass | `make verify` | Before the pull request opens |
| The ratchet checks | `uv run python scripts/check_portable_store.py --strict`, `uv run python scripts/check_access_exceptions.py`, `uv run lint-imports --no-logo`, `uv run pytest -q deploy/database/tests/test_isolation_markings.py`; the components add the raw-site, config-literal and typed-boundary checks beside them | Every commit; a lane leaves each at zero for its service |
| Staging | `make stg-deploy REF=<merge commit>` runs every step including the console walk; `make stg-health` shows every process up | After the merge, before the lane is called done |
| Guides and standards references | `make docs-guides-check` | When a guide or this folder changes |

A lane is done when its service's baseline files are at zero, `make -s test PKG=services/<x>` is green on PostgreSQL
and SQL Server, its use cases are green on the merge commit, a reviewer who did not write it has approved (`DL3`), the
merge has deployed to staging with every process up and the console walk green, and the service's screens have been
opened by hand on staging. The use-case harness starts its own stack on free ports and cannot point at the staging
host today; a `base URL` option for the api layer is listed in the components page under C6 so the staging run can
be the same scripts.

## Standards cited here

`LY1` `LY3` `LY7` `CF2` `CF3` `TN1` `TN2` `AC1` `AC2` `DA1` `DA5` `DA7` `AP1` `MD1` `MD4` `EV2` `EV4` `UI1` `UI2`
`UI6` `OB6` `SC2` `TS1` `TS3` `TS6` `DL2` `DL3` `DL4`. Each is defined on a page under [standards/](../standards/).
