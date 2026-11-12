# Tools and apps use cases

Status: current (design, 2026-11-12). Every use case that connects an app, signs an account in, builds or runs a tool, or
reads the call log, with what each proves, what it merges into and where the SDK, CLI, MCP and console layers stand.

Each page is written as: a short task title; "In this example we will do X. It assumes Y and Z."; numbered steps through
the SDK, the CLI or the console, using the shared steps in the use cases README. The SDK and the team MCP address are the
connecting points: a console step is only written once the same step exists through the SDK.

## The list

States come from runs, not from the registry. "not run" means no run since the console moved Connectors to
`/data/connectors`, My connectors to `/settings/account/connectors` and Tools to `/data/tools`.

| Id | Short title | What it proves | Layers | State |
|---|---|---|---|---|
| uc-013 | An app's key never comes back | A key reaches the system it calls and is never shown to a person or an agent | sdk, cli | page, not run |
| uc-558 | People connect their own Salesforce account | A call acts as the person who asked; an unconnected person gets a link made for them alone; a body never picks a token | api, sdk, cli, ui | api not run; sdk, cli: steps 1 and 2 pass, connect is a gap (no SDK or CLI call); ui pass (11 checks, 2026-11-12) |
| uc-607 | A team connects apps from one catalog | Connectors, the Connect window, an app's page, and a tool that runs with a person's own account | api, sdk, cli, ui | ui open: steps 2 to 46 walk the old page (see the gap list) |
| uc-390 | Connect an app with a key, a password, a token or a client secret | Each sign-in kind reaches the system with the right header, per environment | api, ui | not run |
| uc-394 | Sign an app in once with the team's account | The team account's token is used and refreshed | api, ui | not run |
| uc-395 | Connect a system that needs a certificate | The certificate is presented and the private key never shows | api, ui | not run |
| uc-396 | Add an MCP server behind OAuth | An MCP server signs in once and its tools run through the same executor | api, ui | not run |
| uc-588 | A developer's plugin signs in every way a system asks | A plugin declares its sign-in methods and headers, and its agents call it | api, sdk, cli, ui | not run |
| uc-564 | Turn on the Salesforce plugin | A team's agents work cases and cite articles | api, sdk, cli, ui | not run |
| uc-581 | Query Salesforce seven ways | Queries page and cannot be changed by what an agent types | api, cli, ui | not run |
| uc-627 | Connect Salesforce at the company address | A team's agents query that org | api, ui | not run |
| uc-609 | Review a plugin update | Tools change only after a team accepts the update | api, ui | not run |
| uc-615 | A team admin sets its own app credential | The credential is tested with the admin's account | api, sdk, cli | not run |
| uc-618 | Turn an app off | The window names who uses it; a leaver loses accounts; Replace rotates a key | api | not run |
| uc-617 | An app that fails says why | An expired account, a run waiting for a person and an unknown host each say so | api, ui | not run |
| uc-626 | Apps screens follow what the person may do | Each role sees only the controls it may use; Add account is a manager's | api, ui | not run |
| uc-671 | Connectors for people | One row per app that acts as the person, an app off for the team, a per-chat set | api, ui | not run |
| uc-702 | A person adds a second account of their own | The second account signs in at its own address and becomes their default | api, cli | not run |
| uc-691 | A second org or server signs in at its own address | A call naming the account reaches that org | api | not run |
| uc-694 | Accounts are named and never borrowed | Another person's or team's account, a deleted name and a test run on a live name are refused | api | not run |
| uc-705 | Callers from before several accounts keep working | An old caller is unchanged | api, sdk | not run |
| uc-721 | A connected app writes at once | Writes run until a team admin turns asking on; a turned-off tool says how to turn it on | api, sdk, ui | not run |
| uc-616 | Usage shows only this team's calls | Usage and the call log name whom each call ran as | api, sdk | not run |
| uc-011 | A tool call runs through the registry | A call is logged with its caller; a write without a token is refused | api | not run |
| uc-038 | A failed call says which side failed | Our side, the system's or the network; a test call can reach the real system | api | not run |
| uc-410 | An assistant runs a team's read tools over MCP | Read tools run with an API key; writes, other teams and production are refused | api | not run |
| uc-611 | A developer builds a REST tool and runs it | The tool is built from an address and runs for real | api, sdk, ui | not run |
| uc-531 | A builder adds a Python function tool | It runs sandboxed and is stopped at an unbound tool, a socket, its time and its memory | api, ui | not run |
| uc-012 | Import tools from OpenAPI and MCP | Imported tools call allowed hosts only | api, ui | not run |
| uc-010 | A builder manages a tool module | Create, edit, publish and retire, from the module's page | api, ui | not run |
| uc-040 | Security decides a module review | A module goes live only after Security approves | api, ui | not run |
| uc-101 | Build and debug a tool operation | The workbench sends the request with a typed secret; its policy and inputs save | ui | not run |
| uc-668 | A meeting log saves both or neither | The opportunity and its note are written together or not at all | api | not run |

## Merged, dropped, moved

| Change | Why |
|---|---|
| uc-390, 391, 392, 393 become one page, uc-390 | One story: connect an app four ways and call it. Four stacks cost more than four sections |
| uc-583 folds into uc-395 | Both present a certificate; 583 adds only the plugin wrapper |
| uc-584 folds into uc-588 | Manifest fields are the second half of a plugin's sign-in |
| uc-709 folds into uc-558 | "Changing who signs in" is steps 9 and 17 of 558 |
| uc-698, 699, 700 fold into uc-694 | Each is one refusal of a call that names an account |
| uc-692 and 706 fold into uc-691 | Same flow with another server, or a package |
| uc-693 folds into uc-607 | The Accounts tab row |
| uc-625, 628, 674 fold into uc-607 | Return in any window, turn on in one window and one state per app page are steps of the Connect window and app page |
| uc-703 folds into uc-626 | Add account by role is one of its role checks |
| uc-730 folds into uc-721 | One switch on Approvals completes the writes-at-once story |
| uc-007 and uc-042 fold into uc-011 and uc-616 | A write without a token is a refusal of the registry call; module counts are usage |
| uc-015 folds into uc-010 | The details page is a step of managing a module |
| uc-055, 054, 090, 059 fold into uc-101 and uc-012 | One tool build walk; each only checks a control it passes |
| uc-041, 230, 266, 397 move to Workflows | They prove a workflow step |
| uc-613 moves to Files and documents | The tool reads a file; the file is the subject |
| uc-612 moves to People and access | An install's feature switch is not a tool |
| uc-107, 110 move to Secrets in the Models and keys area | One place for secrets |
| Nothing dropped as dead | Each has a script; none is dropped until its page runs |

## What the layers need

| Layer | Today | Gap |
|---|---|---|
| SDK | `ops.apps` (list, get, add_custom) and `ops.credentials`; accounts, tests and the call log through `ops.raw.tools` | Not checked call by call; the first page that needs an account step names the missing named call |
| CLI | `opsai apps` (uc-607 steps 25 and 26 run it) | Not checked for turning an app on, adding an account or testing one |
| MCP | The team address lists and runs read tools (uc-410) | No tool for a person's own sign-ins or a connect link; not checked further |
| Console | uc-558 ui passes; uc-607 steps 0, 2, 3, 4 and 40 pass; the rest walk ids that moved | Re-read the element ids on `/data/connectors`, `/settings/account/connectors` and `/data/tools`, step 42 onward |

## Product changes the pages now follow

These are the console's current design, not gaps; the old expectation was stale. No product gap is confirmed yet.

| Use case | Step | The page used to expect | The console now |
|---|---|---|---|
| uc-558 | 17 | Turning own accounts back on saves `person` | Saves `person_or_team`, team backup on (`app-settings-tab.tsx:58`) |
| uc-558 | 18 | An admin connects their own account on the app's page | Own sign-in is on My connectors; the app page's Connect is the team's (`app-page.tsx:75`) |
| uc-607 | 4, 40 | The header and the catalog card read Connected after the team signs in | On an app where each person signs in, they show the viewer's state ("You: Needs sign-in"); the team row reads Connected |

## Open for the next pass

uc-607 steps 42, 6, 7, 44, 46 and the steps after them time out or read old ids; none of those failures is yet shown to be a
product defect. Next item: uc-607 step 42 (the Connected and Available views for an app each person signs in to), then step 6
(James on My connectors).
