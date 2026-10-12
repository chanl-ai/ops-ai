# Mailbox adapter: Graph delta mail into threads and runs

Status: E6, 2026-10-10; race closed, Postgres measured 2026-10-11; no real tenant. Tests `tests/api/test_mailbox*.py`
(no model calls), measurement `experiments/mailbox_postgres_cost.py`, fixture `scripts/make_mailbox_fixture.py`.

## Verdict

A mailbox adapter can feed Graph delta mail into the four thread calls with no duplicate cases, and no graph knows
that mail exists: a graph receives an `email` whose attachments are file references.

## What holds

| Failure mode | Result |
|---|---|
| Redelivery, with or without angle brackets, domain in any case, opens no second case | holds |
| Two replies in one poll on a running case queue in order and are delivered in order when the run ends | holds |
| Delta request fails mid-poll: cursor not saved, replay creates no duplicate case or inbox entry | holds |
| No Message-ID: key from sha256(sender, received time, subject); its redelivery opens no second case | holds |
| Paused deployment opens no case (deferred, opened after unpause); replies to existing cases still deliver | holds |
| Reply on a finished case opens a follow-up thread with `parent_thread_id` | holds |
| Reply on a waiting case delivers at once and restarts its E5 SLA timers | holds |
| Two processes: a reply arrives after the case is created, before its first run; or a lease is taken mid-delivery | holds (was a second case) |

Each step can repeat after a crash: find-or-create on a unique `external_key` (`deployment id:Message-ID`) in one
transaction, run id derived from that key, inbox unique on (thread, Message-ID), attachment ids derived from the
message, ledger written only after handling, cursor saved only after the last page.

## Numbers

PostgreSQL scratch database, asyncpg checkpointer, scripted model, 100-message fixture (102 delta items):

| Run | Messages/s | SQL statements per item | Checkpointer calls per item |
|---|---|---|---|
| First poll (82 cases opened and run to review) | 13 | 31.8 | 16.3 (puts 5.4, writes 5.9, reads 4.2, fence 0.8) |
| Full replay (all duplicates) | 615 | 1.0 | 0 |

SQL counts SQLAlchemy statements; each checkpointer call adds two to four asyncpg ones. SQLite showed 22 per item
before fences, leases and timers. The adapter's own cost is one ledger read per message.

## Gotchas

| Gotcha | Handling |
|---|---|
| Message-IDs vary in brackets and case | Strip brackets, lower-case the domain, keep the local part (RFC 5322) |
| Graph sends `@removed` for deletes and folder moves | No-op; a move back returns as a duplicate |
| Saving the delta link per page loses mail if a later page fails | Save only after the final page |
| One message sent to two deployments | Key includes the deployment id, so each gets its own case |
| Reply finds no case while its first message is mid-delivery (the ledger is written after the run) | Look up the case by the referenced message's external key, which exists from find-or-create |
| A case with no run yet looked finished, so a reply opened a follow-up | No checkpoint yet means not started: the reply queues for the first run's end |
| Lease taken between a delivery's check and its write | `deliver` and `Leases.acquire` take one per-thread advisory lock (`thread_lock`) |
| Pause stops new cases only | Holding replies too needs a second flag |
| Synthetic keys merge two messages with identical sender, time, subject | Accepted for the fallback |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| `GraphMailSource` against a test tenant, including large attachments (inline `contentBytes` is size-limited) | Channel go-live |
| `deployments` and `channel_*` tables | Other channels (widget, API, MCP) reuse the same find-or-create and inbox |
