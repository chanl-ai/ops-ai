# Engineering standards

Status: target state. Every rule is the bar code must meet; code that misses one is a defect to fix, and a review
cites the rule id. This page is the index: the rules themselves, each with the reason, a real example from this
repository of code that breaks it, the pattern to follow (also from this repository) and the check that enforces it,
live on the pages under [standards/](standards/). What the system does is decided by the rest of this folder
([architecture](README.md), [service map](service-map.md), [data](data.md), [identity and tenancy](identity-and-tenancy.md),
[roles and permissions](roles-and-permissions.md), [logging and data writes](logging-and-data-writes.md), the
[decision records](decisions/)); where a standards page and one of those disagree, that page wins and the standard is
corrected.

## How to read a rule

| Term | Meaning |
|---|---|
| Id | Two letters for the area and a number, `DA5`. Ids are frozen from this version: a retired rule keeps its id and says "retired"; a new rule takes the next number |
| Citing a rule | Write the id in backticks, `` `DA5` ``. `scripts/check-standards-refs.mjs` fails on an id in backticks that no page defines, and on an agent or folder guide that links no standards page |
| Rule | One sentence a reader can test code against |
| Why | What goes wrong without it, in plain words |
| Today | A real example from this repository, with `file:line`, of code that breaks the rule; "no breach" when none is known |
| Pattern | The best code in this repository that follows it, with `file:line` |
| Check | The script, test or CI step that fails when the rule is broken. "No check yet" is followed by what the check should be |
| Ratchet | A check with a committed baseline: a new finding fails, and a fixed one must leave the baseline in the same change |
| Kit | `packages/ops_service_kit`, the one place a service gets settings, logging, the envelope, paging and errors |

## The pages

| Page | Ids | Covers |
|---|---|---|
| [Layers and ownership](standards/layers.md) | `LY1` to `LY9` | The onion inside a service and across the product; one owner per job; names; ports |
| [Configuration](standards/configuration.md) | `CF1` to `CF6` | One settings object; no literal hosts, ports or timeouts; fail at start; secrets; safe defaults |
| [Tenant isolation and access](standards/tenancy-and-access.md) | `TN1` to `TN5`, `AC1` to `AC5` | Row-level security on every tenant table; `isolated_tx` on every transaction; `can()` as the only decision |
| [Data access](standards/data-access.md) | `DA1` to `DA13` | One transaction per request; Core statements; paging and joins in SQL; indexes; migrations; retention |
| [API contracts and models](standards/api-and-models.md) | `AP1` to `AP7`, `MD1` to `MD4` | Typed, authenticated, idempotent routes; one envelope; `extra="forbid"`; one model per contract |
| [Events, the relay and workers](standards/events-and-workers.md) | `EV1` to `EV6` | Outbox in the same transaction; one relay; idempotent receivers; loop health; one tenant per item |
| [Console, SDKs and CLI](standards/console-and-sdk.md) | `UI1` to `UI7` | No browser-side joins or `.reduce()`; hooks only; server paging; generated SDKs; CLI over the client |
| [Errors, logging and observability](standards/observability.md) | `OB1` to `OB6` | Kit logging; one request line with ids; typed errors; up and ready; timeouts |
| [Security](standards/security.md) | `SC1` to `SC6` | Two gateways; audit in the same transaction; secrets write-only; dependencies; nothing committed that identifies a customer |
| [Tests](standards/testing.md) | `TS1` to `TS8` | Failure modes first; a budget per change; seen failing once; public seams; use cases per layer |
| [Delivery, deploy and upgrade](standards/delivery.md) | `DL1` to `DL9` | Branch and pull request; one gate; a separate reviewer; staging on every merge; tagged production; proven upgrades |

## The layers in one picture

```
console, CLI ──► SDK (generated + nouns) ──► HTTP ──► api ──► app ──► store ──► ops_store ──► database
                                                               └──► domain (pure rules)
                            adapters (other services, the two gateways) ◄── app, through a port
```

## One owner per job

Before adding anything that does one of these jobs, use the owner (`LY7`).

| Job | Owner |
|---|---|
| Settings | `ops_service_kit.settings` |
| Log setup and redaction | `ops_service_kit.logging` |
| Envelope, errors, paging | `ops_service_kit.http`, `ops_service_kit.errors` |
| Caller and token checks | `ops_identity` |
| Access decisions | `ops_access.can` |
| Tenant and team context, isolated transactions | `ops_store.isolation`, `ops_store.team_scope` |
| Database differences | `ops_store.dialect` |
| Audit entries and events | `ops_store.audit`, `ops_store.outbox` |
| Calls to another service | `ops_identity.ServiceClient` |
| Model calls | models-service, through `ops_service_kit.model_calls` or the agent kernel |
| Tool and outside-system calls | tools-service |
| Secret values | `ops_service_kit.credentials` over `ops_policy.CredentialStore` |

## Every rule and its check

Yes: a check in this repository fails when the rule is broken. Partial: a check exists for some services, some shapes,
or runs only on a full CI plan or nightly. No: nothing fails today; the page says what the check should be. Counts:
91 rules, 37 yes, 29 partial, 25 no.

| Id | Rule | Check |
|---|---|---|
| `LY1` | Imports point inward | partial |
| `LY2` | A route does one thing | no |
| `LY3` | Database code lives in the stores | yes |
| `LY4` | Services never import each other | yes |
| `LY5` | Packages never import a service | yes |
| `LY6` | Console and CLI call the platform through the SDK | partial |
| `LY7` | One owner per job | partial |
| `LY8` | Names say what the module does | no |
| `LY9` | Outside systems sit behind a port | no |
| `CF1` | One settings object per process | partial |
| `CF2` | No literal host, port, URL, model or timeout | partial |
| `CF3` | A missing required setting stops the process | yes |
| `CF4` | Secrets come only from the secret store | yes |
| `CF5` | The default is the safe production value | partial |
| `CF6` | The console reads the environment in one file | yes |
| `TN1` | Every tenant table is marked and policed | yes |
| `TN2` | Every read and write runs inside an isolated transaction | partial |
| `TN3` | Team scope comes from one helper | yes |
| `TN4` | Tenant from the token, team from the header, 404 for the rest | yes |
| `TN5` | A wider read names its reason | yes |
| `AC1` | Every decision goes through `can()` | yes |
| `AC2` | An exception is written down before it exists | yes |
| `AC3` | The roles page changes with the code | yes |
| `AC4` | Policy values are read, never assumed | yes |
| `AC5` | Service calls carry the least scope | partial |
| `DA1` | One transaction per unit of work | no |
| `DA2` | Statements are built with Core, never with strings | partial |
| `DA3` | Database differences live in one module | yes |
| `DA4` | No query inside a loop | no |
| `DA5` | Lists are paged and filtered in SQL | no |
| `DA6` | Every route has a statement budget | no |
| `DA7` | Foreign keys and filter columns are indexed | no |
| `DA8` | One migration chain per service, one head | partial |
| `DA9` | Every migration downgrades and runs on both databases | yes |
| `DA10` | A column is dropped one release after it stops being read | no |
| `DA11` | Request paths are async end to end | no |
| `DA12` | A write states the state it expects | no |
| `DA13` | Append-only tables have retention and idle polls write nothing | no |
| `AP1` | Every route declares its responses; the document matches | yes |
| `AP2` | One envelope for success and one for failure | yes |
| `AP3` | Every route is authenticated | partial |
| `AP4` | A write is safe to repeat | no |
| `AP5` | Contracts change by addition | no |
| `AP6` | An error message carries nothing a caller should not see | partial |
| `AP7` | Route ids and tags come from the kit | yes |
| `MD1` | Request bodies refuse unknown fields | no |
| `MD2` | One model per contract, generated everywhere else | yes |
| `MD3` | Validation is never skipped on outside input | no |
| `MD4` | A value that crosses a layer is a model | partial |
| `EV1` | The event commits with the change | yes |
| `EV2` | One relay, wired once | no |
| `EV3` | A receiver tolerates a repeat | yes |
| `EV4` | Every loop reports its health | partial |
| `EV5` | Workers claim with the dialect and lease what they hold | yes |
| `EV6` | A worker enters one tenant per item | yes |
| `UI1` | No joins, counts or sums in the browser | no |
| `UI2` | One direction: pages, hooks, contract, client | yes |
| `UI3` | Sample data lives in the mock | partial |
| `UI4` | Lists page on the server through the shared parameters | yes |
| `UI5` | Every data surface has its three states | yes |
| `UI6` | The SDKs are generated, and both languages move together | yes |
| `UI7` | The CLI calls the client | no |
| `OB1` | Logs go through the kit | partial |
| `OB2` | One request line with the ids and the counts | partial |
| `OB3` | Errors are typed, coded and actionable | partial |
| `OB4` | Up and ready are two answers | no |
| `OB5` | Background health is part of health | partial |
| `OB6` | Every outbound call has a timeout and a bounded retry from settings | no |
| `SC1` | Two gateways, no other egress | partial |
| `SC2` | A change to access leaves an audit entry in the same transaction | no |
| `SC3` | A secret is written once and never returned | partial |
| `SC4` | Every dependency is reviewed | partial |
| `SC5` | Nothing committed identifies a customer or opens a door | yes |
| `SC6` | Tests never open a real connection | partial |
| `TS1` | Name the failure modes, then one test each | yes |
| `TS2` | A budget per change | no |
| `TS3` | Every new test is seen failing once | yes |
| `TS4` | Assert through the public seam | partial |
| `TS5` | A use case per layer | yes |
| `TS6` | Scripted model, throwaway database, both databases | partial |
| `TS7` | Tests and code by different hands | yes |
| `TS8` | No test of a library | no |
| `DL1` | A branch, a pull request, never the trunk | yes |
| `DL2` | One gate, the same locally and in CI | partial |
| `DL3` | A reviewer who did not write it | no |
| `DL4` | Every merge reaches staging under the real migrations | partial |
| `DL5` | Production gets a tagged commit staging ran | partial |
| `DL6` | An upgrade from the previous release is proven | partial |
| `DL7` | Commits and What's new explain themselves | yes |
| `DL8` | Docs change with the code | yes |
| `DL9` | Every check is seen failing once | yes |

## Where the examples come from

The "Today" examples were verified against the code on this branch. Two read-only audits supplied the counts quoted
on the pages: a deployability audit of which design rules a merge can break (30 rules, 16 with a failing check, 12 with
none) and a database audit of queries per screen (200 to 600 statements per screen, 59 browser-side joins, 8 missing
indexes). Both were measured on 2026-11-14; the code wins where they disagree.

## Sources

| Source | Used for |
|---|---|
| The Twelve-Factor App, III "Config" (12factor.net/config) | `CF1` to `CF3` |
| OWASP Application Security Verification Standard 4.0.3 | V4 access (`AC1`, `TN4`), V5 input (`DA2`, `MD1`), V7 errors and logging (`AP6`, `OB1`), V13 configuration (`CF4`) |
| AICPA SOC 2 Trust Services Criteria, CC6, CC7, CC8 | `AC1`, `SC2`, `DL1` to `DL3` |
| SQLAlchemy 2.0 docs, "Working with transactions and the DBAPI", "Using SELECT statements" | `DA1`, `DA2`, `DA11` |
| Pydantic v2 docs, "Models" and "Configuration: extra" | `MD1`, `MD3` |
| Percival and Gregory, *Architecture Patterns with Python* (cosmicpython.com) | `LY1`, `LY2`, `DA1` |
| Alembic docs, "Branches" and merge revisions | `DA8` |
| Inozemtseva and Holmes, "Coverage is not strongly correlated with test suite effectiveness", ICSE 2014 | `TS1`, `TS3` |
