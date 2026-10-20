# Mailbox adapter: Graph delta mail into threads and runs

Status: historical. The v1 mailbox adapter, its tests and `experiments/mailbox_postgres_cost.py` were removed on 2026-10-18 (c-212); mail now starts workflows through the Email received trigger (c-187). Measured: E6 2026-10-10; race closed and Postgres measured 2026-10-11; dev fake source 2026-10-15 (c-057).
Tests `tests/api/test_mailbox*.py` (no model calls), measurement `experiments/mailbox_postgres_cost.py`, fixtures
`scripts/make_mailbox_fixture.py`. SQL counts SQLAlchemy statements; a checkpointer call adds two to four asyncpg ones.

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

## Gotchas

| Gotcha | Handling |
|---|---|
| Message-IDs vary in brackets and case | Strip brackets, lower-case the domain, keep the local part (RFC 5322) |
| Graph sends `@removed` for deletes and folder moves | No-op; a move back returns as a duplicate |
| Saving the delta link per page loses mail if a later page fails | Save only after the final page |
| Reply finds no case while its first message is mid-delivery (the ledger is written after the run) | Look up the case by the referenced message's external key, which exists from find-or-create |
| A case with no run yet looked finished, so a reply opened a follow-up | No checkpoint yet means not started: the reply queues for the first run's end |
| Lease taken between a delivery's check and its write | `deliver` and `Leases.acquire` take one per-thread advisory lock (`thread_lock`) |

## Dev stack: the fake source

| Piece | How |
|---|---|
| Source | `OPS_MAILBOX_SOURCE=fake` (dev only, refused outside dev): `FileMailSource` over `OPS_MAILBOX_FAKE_DIR/<deployment id>/*.json`, default `.run/fake-graph`, re-read on every poll; each file is one Graph delta item or a list. `none`, the default, refuses to poll: no tenant is configured |
| Poll | `POST /v1/deployments/{id}/poll` runs the adapter in this process as the caller and returns the report. A thread call that refuses a message (a deployment on a graph not published yet) answers 400 naming it and keeps the cursor, so the message is tried again |
| Deployment | `seed/deployments.json` (`OPS_DEPLOYMENTS_SEED_FILE`, set by `scripts/stack.sh`): `dep_levy_mailbox` on `levy-intake`, upserted at start without checking the graph |
| Message | `scripts/drop_levy_email.py` writes `tests/fixtures/mailbox/levy_notice.json` (a garnishment notice; its PDF has a text layer naming three persons, two of them fake-bank customers) into the folder and polls; `--as <email>` signs in through platform-service |

Left: `GraphMailSource` against a test tenant, including large attachments (inline `contentBytes` is size-limited),
which is channel go-live; the `deployments` and `channel_*` tables serve the other channels' find-or-create and inbox.
