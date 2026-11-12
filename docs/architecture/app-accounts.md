# Several accounts per app

Status: current design, 2026-11-11. Code cited at commit 81c9883a. This page covers how a team or a person holds
several named accounts of one app (two Salesforce orgs, two GitHub servers), how each account says what it points at,
and how every call picks exactly one account. Connecting and calling a tool end to end is in
[tool lifecycle](tool-lifecycle.md); who may manage connections is in [roles and permissions](roles-and-permissions.md);
the layers around accounts (providers, plugins, triggers) are in [integrations in layers](integrations.md).

## Status by part

| Part | Built | Where |
|---|---|---|
| Named accounts per app per team, one name per app enforced by the database | Built | `services/tools-service/migrations/versions/0071_account_key.py:26`, `services/tools-service/src/ops_tools/store/connections.py:124`, `:304` |
| What an account points at (`identity`, `pointsAt`) | Built | `services/tools-service/src/ops_tools/plugins/host.py:115`, `:141`; `services/tools-service/src/ops_tools/apps.py:1942` |
| Manifest field `connection.identity`, validated | Built | `packages/ops_plugin_sdk/src/ops_plugin_sdk/manifest.py:143`, `packages/ops_plugin_sdk/src/ops_plugin_sdk/validate.py:360` |
| Same-place warning | Built | `services/tools-service/src/ops_tools/apps.py:513`; `apps/console/src/components/connections/account-settings-dialog.tsx:98` |
| Account choice per call, with refusals | Built | `services/tools-service/src/ops_tools/plugins/host.py:832`, `:859`, `:919`; `services/tools-service/src/ops_tools/gateway_calls.py:174-182` |
| Accounts map from steps, agents and chats | Built | `services/agents-service/src/ops_agents/domain/accounts.py:12`, `packages/ops_engine/src/ops_engine/compiler.py:504-536`, `services/agents-service/src/ops_agents/api/engine_host.py:131` |
| Publish check of named accounts | Built | `services/agents-service/src/ops_agents/api/account_names.py:39`, `services/agents-service/src/ops_agents/api/engine_lifecycle.py:120`, `services/agents-service/src/ops_agents/api/routers/agents.py:671` |
| The model is told the account in use | Built | `services/agents-service/src/ops_agents/api/apps_line.py:39-48` |
| Team default (star) and person default | Built | `services/tools-service/src/ops_tools/apps.py:2209`, `services/tools-service/src/ops_tools/connections/routes.py:102`; `apps/console/src/components/connections/app-accounts-tab.tsx:93` |
| A person's second own account with a name and address | Built | `services/tools-service/src/ops_tools/connections/routes.py:126` |
| Delete refused while a definition names the account | Built | `services/tools-service/src/ops_tools/connections/service.py:676-700` |
| "Who signs in" choice and "Use only for test runs" | Built | `apps/console/src/components/connections/who-signs-in.tsx:38`, `apps/console/src/components/connections/connect-window.tsx:390` |
| Apps that run inside another app (`runs_on`, `requires`) | Built | `packages/ops_plugin_sdk/src/ops_plugin_sdk/manifest.py:147-151`, `services/tools-service/src/ops_tools/plugins/host.py:201`, `:955-958` |
| Sharing an account with other teams | Designed, not built yet | — |
| Limiting an account to chosen roles | Designed, not built yet | — |
| Read-only account (refuse every write through it) | Designed, not built yet | — |

## What an account is

An account is one row of the tools service's `connections` table for one app in one team
(`services/tools-service/src/ops_tools/store/connections.py:44`). There is no separate accounts table.

| Field | Meaning | Built |
|---|---|---|
| Name (`account_name`) | What people, steps and agents call it: "EU org", "Platform org", "Logistics site". One per app per team, compared case-folded | Built. The stored `account_key` and the filtered unique index `uq_connections_account_key` (PostgreSQL and SQL Server) hold the rule (`0071_account_key.py:26`, `:70-71`). The routes raise `account_name_taken` with the same message everywhere (`store/connections.py:304-307`) |
| Who signs in | Shared team login, or each person signs in with their own login | Built (`who-signs-in.tsx:38`) |
| Test only | A test account is used only by test runs and cannot be the team default | Built (`connect-window.tsx:390`, `:513`; `plugins/routes.py:326`) |
| Auth config | Ops AI's app, or the team's own OAuth app | Built |
| Where it signs in | The sign-in address the account keeps for itself, when the app allows one per account | Built. The first turn-on on Ops AI's app keeps the address as a default, so a second org signs in at its own address (`plugins/routes.py:302`). A binding that already holds the address as fixed stays fixed |
| What it points at (`identity`) | The values that tell this account from the app's others, shown under its name on every surface | Built (see below) |

### What it points at

`account_identity` (`plugins/host.py:141`) builds one list per account, `[{label, value, shown}]`, and every surface
reads it: the Accounts tab, Connectors › Mine, the chat picker, the step and agent pickers, and the CLI
(`sdk/python/src/ops_ai/_cli/apps.py:35`). `pointsAt` is the same list without who signed in
(`services/tools-service/src/ops_tools/apps.py:463`, `:1942`).

| Source, in order | Example |
|---|---|
| The settings the plugin's `connection.identity` names (at most three, none secret; `validate.py:360-370`) | Salesforce: `instance_url` |
| With none declared: what the sign-in filled, then where the account signs in (`sign_in_values`, `plugins/host.py:115`) | An org address, a server host |
| A custom app: the host of its base URL | `api.example-freight.test` |
| Last: who signed in | `signed in as a.lee` |

A row's identity is never empty when any of these holds a value. Two accounts that point at the same place both stay;
the later one carries `samePlaceAs` and shows a warning (`apps.py:513-515`), because a team may keep a read login and a
write login to one org.

## How a call picks its account

The tools service picks the account for every call and checks that the caller may use it. Chats, agents and workflow
steps never pick or check an account themselves; they send what someone chose.

```
step's or chat's choice  >  agent's choice  >  person's default  >  team's default
```

| Order | Source | Set by | Where |
|---|---|---|---|
| 1 | A workflow step's `accounts` map, app id to account name | Builder, in the step's settings | `packages/ops_engine/src/ops_engine/compiler.py:504-536`, `packages/ops_engine/src/ops_engine/ports.py:41` |
| 1 | A chat's pick per app, kept on the chat | The person, with Change in the chat's Connectors picker | `services/agents-service/src/ops_agents/api/routers/chat_connectors.py:73-87`; `apps/console/src/components/chat/connectors-picker.tsx:100` |
| 2 | An agent's `accounts` map, pinned with the agent's version | Builder, on the agent's settings | `services/agents-service/src/ops_agents/api/agent_registry.py:128`; `apps/console/src/components/agents/agent-settings.tsx:213` |
| 3 | The person's default, when the call acts for a person with their own sign-ins | The person, on Connectors › Mine | `services/tools-service/src/ops_tools/plugins/host.py:797` |
| 4 | The team's default | A connection manager, with the star on the row | `apps.py:2209` |

A step and a chat never run together, so they share order 1. `chosen_accounts`
(`services/agents-service/src/ops_agents/domain/accounts.py:12`) is the one place that merges the layers: the step's
choice over the chat's over the agent's. The agents service sends the whole map as `runContext.accounts` on every
call (`services/agents-service/src/ops_agents/activities/gateway.py:43`, `:76-92`); the tools service reads the entry
for the call's own app (`gateway_calls.py:357`, `plugins/host.py:876`). An older caller's single string
`runContext.account` is still read (`gateway_calls.py:356`).

### Rules the server applies to a named account

`_named` (`plugins/host.py:832`) holds these. Pickers list only what the caller may name, and the server checks every
name on the call whatever the picker showed.

| Case | Result |
|---|---|
| The name is not one of the team's accounts of the app, or names another team's | Refused `ACCOUNT_NOT_FOUND`. A call never falls back to the default |
| The name is one person's own account and the call does not act for that person | Refused `ACCOUNT_NOT_YOURS`. A step or a scheduled run acts for nobody, so it uses team accounts only |
| A test run names a live account | Uses the app's test account (`connections/records.py:60`), else refused `SANDBOX_REQUIRED` |
| A run as the team account after a person picked one of their own | The person's pick is dropped; the step's choice or the team default applies (`domain/accounts.py:32`) |
| A package app (one that `runs_on` another) is named directly | Refused: it has no accounts of its own, so a call names an account of the app it runs on (`plugins/host.py:969-974`) |
| The chosen account lacks the package's required objects | Refused, naming what is missing (`plugins/host.py:999-1005`); the picker greys the org ("not installed", `account-select.tsx:58-66`) |

With no name, a person signed in to two or more accounts of an app with no default is asked which
(`ACCOUNT_CHOICE_NEEDED`, `plugins/host.py:884`); chat draws a card with each account's address
(`apps/console/src/components/chat/connection-required-card.tsx:297-311`), and "Always use it" makes the pick the
person's default.

### A step naming an account

```mermaid
sequenceDiagram
  participant Eng as engine (agents-service)
  participant Host as engine_host.call
  participant GW as tools-service /v1/calls
  participant FC as PluginHost.for_call
  participant App as Outside app
  Eng->>Host: tool step, accounts {salesforce: "EU org"}
  Host->>Host: chosen_accounts(agent, step) → runContext.accounts
  Host->>GW: POST /v1/calls {runContext.accounts}
  GW->>FC: accounts map, run (test or live), person
  FC->>FC: entry for this call's app → _named
  alt unknown, not yours, or test run with no test account
    FC-->>GW: refused (ACCOUNT_NOT_FOUND / ACCOUNT_NOT_YOURS / SANDBOX_REQUIRED)
    GW-->>Host: error, nothing sent to the app
  else allowed
    FC-->>GW: module with that account's connection and hosts
    GW->>App: call signed with that account
    GW-->>Host: result; gateway_calls row names the account
  end
```

### What the model sees

The model never picks an account. The apps line in the prompt names the account in use when an app has two or more:
"Salesforce: on · uses EU org (eu.my.salesforce.com)" (`apps_line.py:39-48`), with where it points and never who
signed in. Asked in words for another org, the model says which account it used and that Change in Connectors picks
another.

## Defaults

| Default | Who sets it | Stored | Where |
|---|---|---|---|
| Team default | Whoever holds `connections.manage`, with the star on the row or `makeDefault` on add. A test account cannot be one | The binding's `connection_id` | `apps.py:2209`, `:2237`; `app-accounts-tab.tsx:93` |
| Person default | The person, on Connectors › Mine. Always one of their own accounts | Their pinned sign-in | `connections/routes.py:102`; `plugins/host.py:797-805` |
| New account on add | Not the default unless `makeDefault` is set | — | `apps.py:2237` |
| Who signs in | Each person signs in, unless the team chooses a shared team login (CLI default `each`) | The account's owner value (team or each person) | `sdk/python/src/ops_ai/_cli/apps.py:30` |

## Renaming and deleting

Renaming never rewrites a draft or a published workflow or agent version. A published version that names the old
name keeps running and is refused `ACCOUNT_NOT_FOUND` at the call; its next publish fails with `account_name_unknown`
naming the step until the step names the new name (`account_names.py:1-4`, `:39-64`). The console asks how many drafts
and published versions name an account before a rename (`GET /v1/workflows/definitions/account-uses`,
`services/agents-service/src/ops_agents/api/routers/engine.py:431`).

Deleting an account is refused with `account_in_use` while any draft or published version names it, with the counts
and the names of the workflows and agents (`connections/service.py:676-700`).

## API

| Route | Does | Where |
|---|---|---|
| `GET /v1/apps/{app}/accounts` | The team's accounts with `identity` and `pointsAt`; `usable=1` and `name=` answer whether a step or agent may name one | `apps.py:2217` |
| `POST /v1/apps/{app}/accounts` | Add an account by name; `makeDefault` optional | `apps.py:2232` |
| `PUT /v1/apps/{app}/accounts/{id}/team-default` | Make it the team's default | `apps.py:2209` |
| `PATCH`, `DELETE /v1/apps/{app}/accounts/{id}` | Rename or change settings; delete | `connections/routes.py:54`, `:62` |
| `PUT /v1/apps/{app}/accounts/{id}/default` | The caller's own default | `connections/routes.py:102` |
| `GET /v1/me/accounts` | The caller's own accounts | `connections/routes.py:112` |
| `POST /v1/me/accounts/{id}/another` | Another own account, with an optional name and address; no body keeps the older behaviour | `connections/routes.py:126` |
| `PUT /threads/{id}/connectors` with `accounts` | The chat's pick per app | `chat_connectors.py:85-87`, `:207` |
| CLI `opsai apps accounts APP`, `opsai apps default APP ACCOUNT [--mine]` | List with what each points at; set a default | `sdk/python/src/ops_ai/_cli/apps.py:35-37` |

## Errors

| Code | Status | When |
|---|---|---|
| `ACCOUNT_NOT_FOUND` | 404 | A named account does not exist in the team |
| `ACCOUNT_NOT_YOURS` | 403 | A named account is another person's own |
| `SANDBOX_REQUIRED` | 409 | A test run names a live account and the team has no test account |
| `ACCOUNT_CHOICE_NEEDED` | 403 | A person holds two or more accounts of the app and chose no default |
| `account_name_taken` | 409 | Another account of the app in the team holds the name |
| `account_name_unknown` | 422 | Publishing a definition that names an account the team does not have |
| `account_in_use` | 409 | Deleting an account a draft or published version names |

The console shows each in words (`apps/console/src/lib/failure-words.ts:13`,
`services/agents-service/src/ops_agents/api/error_words.py:48`, `:72`).

## Designed, not built yet

| Part | Rule |
|---|---|
| Share an account with other teams | An account belongs to the team that added it. Its managers may share it with other teams in the same tenant for use only: the other team sees it in pickers and on the Accounts tab marked "Shared by" the owning team, and cannot edit, rename or delete it. Sharing and stopping a share are audited, and stopping is blocked while that team's steps or agents name the account. `for_call` accepts an account owned by or shared with the caller's team |
| Limit an account to roles | Optional "Who in the team may use it": everyone, or chosen roles. Others do not see it in pickers and the server refuses a call that names it, checked in `for_call` against the caller's roles |
| Read-only account | A switch on each account, "Allow changes in this org", on by default. Off, every write tool through the account is refused with "This org is read-only in Ops AI. An admin can allow changes in the account's settings." Write approval still applies on top |
| Delete blocked by shares | Once sharing exists, delete is also blocked while a share names the account |

Not covered by this design: moving an existing account to another org (add a new account, then delete the old one),
and switching tools on per account (tools stay on per app for the team).
