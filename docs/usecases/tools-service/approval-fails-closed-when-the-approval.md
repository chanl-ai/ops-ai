# Approval fails closed: when the approval rules cannot be read, a write that needs approval is refused and never runs

Status: draft. Id: `uc-754`. Service: `tools-service`. Layers: api.

Short title: Approval fails closed: when the approval rules cannot be read, a write that needs approval is refused and never runs

## Story

As a security admin, I want a write that needs approval to be refused when the approval rules cannot be read.

## People

| Person | Role | Does what |
|---|---|---|
| Account desk agent | agent | Asks for a write in chat |

## In this example

tools-service starts with no platform client, so the team approval rules cannot be read. A write module with no approval switch of its own is asked for in chat.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | With the rules unreadable a write is held or refused and never runs | api | 3, 4 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Mode switch

`MODE=mock` only: this case needs no model or system beyond the scripted model and the mock upstream.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A write whose own switch asks for approval is asked for | Waits on a card |
| 2 | The upstream is read | No hold |
| 3 | A write with no switch of its own is asked for with the rules unreadable | Held on a card or refused |
| 4 | The upstream is read | Still no hold |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-754-api.py` | red on this base (step 3: the write ran, hold placed); expected green after f2c59b2b |

## Open

On this base the write runs with the rules unreadable. After the fail-closed change the write answers 503 `approval_rules_unavailable`; step 3 then needs to accept that refusal (it already accepts a refused status or a card).

## Non-vacuous check

Steps 1 and 2 show a gated write waits, so steps 3 and 4 can only fail by the unreadable-rules path running the write.
