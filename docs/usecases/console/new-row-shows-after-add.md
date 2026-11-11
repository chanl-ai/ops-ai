# A new row shows right after it is added

Status: current. Id: `uc-710`. Service: `console`. Layers: ui.

A list paged on the server sorts by name and holds a page at a time, and a search narrows it. A row the person adds
in place can therefore land on another page or outside the search. The shared data table (`DataTableWithViews`,
`created` with `useCreatedRows`) shows each new row first, marked New, until the person pages, searches, filters or
sorts; then it follows the list again. A write sent after the row was shown that names its id (a remove, revoke,
archive, bulk delete or edit) lets it go at once, so a removed row never stays on screen marked New. The Egress hosts list is the example here, because tools-service returns the
listed entry from the add (`POST /v1/egress/hosts`, `entry`). Every paged list that adds in place uses the same prop,
and the console standards check (rule 22) fails a list that adds rows without it.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service and tools-service on the run's database | the harness starts them (`platform: true, tools: {}`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Twelve hosts that sort before it are listed; the Security admin adds `zz-late…` | the row shows on the first page, marked New |
| 2 | The admin sorts the list by host | the new row leaves, following the sort |
| 3 | The admin types a search the new host does not match, then adds `zz-search…` | the row shows, marked New |
| 4 | The admin changes the search | the new row leaves, following the search |
| 5 | The admin adds a host already listed on the page | 200, the row shows once, marked New |
| 6 | The admin adds `zz-remove…`, which sorts onto a later page, then removes it from its row menu | the row leaves at once and the server no longer lists it |
| 7 | The admin adds a private range, a list paged in the browser | the row shows, marked New |
| 8 | A member opens the page | the list shows, with no Add host |

Screenshots of steps 1, 3 and 6 at 1440 and 390 are written to `.logs/usecases/uc-710/`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-710-ui.mjs` | passing |

## Non-vacuous check

`a new host that sorts onto a later page shows right after it is added, marked New`: without the table's `created`
rows (or with the add returning no `entry`), the new host sits on page 2 and the check fails; it failed so before the
fix.

`a new host removed right after it is added leaves the list at once, not left marked New`: without the table passing
finished writes to `created.written`, the removed host stays at the top marked New, because the refetched first page is
unchanged; it failed so before the fix.
