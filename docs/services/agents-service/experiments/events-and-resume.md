# Events and resume: a thread event log, and reviews decided only through decide

Status: done, 2026-10-11. Tests: `tests/api/test_events.py`, `test_graphs.py`, `test_self_approval.py`,
`test_step_up_sso.py`, `tests/conformance/`; use cases uc-001 to uc-005, uc-008, uc-009.

## Verdict

The prerequisite for moving chat onto the graph calls holds. Every run event is stored in the designed shape as it
happens, a client can re-attach from a cursor, a team can follow its threads' lifecycle, and a review-owned step can
no longer be resumed around its decision.

## What holds

| Failure mode | Proof |
|---|---|
| Events exist only after the run ends | A node reads the log mid-run on PostgreSQL and finds `started` and all six extract events; it fails with writes deferred |
| `seq` restarts per run | The resume run continues the thread's numbering, after one `decided` event |
| Re-attach repeats or skips | `after=` returns exactly the stored suffix, in the designed shape |
| Team stream leaks other teams | Only the caller's team, lifecycle types only; a cursor returns what follows |
| A review resumed on the run stream | 409 `resume_via_review`; watched to pass with the gate removed |
| The workflow's own principal approves | Approvals route 403; watched to pass without the check |
| Two people sharing a display name are one | Requester recorded and compared by subject; watched to fail by name |
| SSO step-up refused by money decisions | `POST /v1/auth/step-up/sso` mints from the IdP callback; a money approval with it succeeds; another account's code is 401 |

## Decisions

| Decision | Detail |
|---|---|
| One log, two readers | `thread_events` (migration 0015): `seq` per thread for re-attach, a global `position` for the team stream's cursor |
| Old stream kept | `runs/stream` still sends `{event, runId, seq}` frames for one release; the log and its routes use the designed shape |
| Re-attach ends with the run | Not at the first `waiting`: the paused node's own end event comes after it |
| Decide owns review resumes | Decide mints the approval token from the input the thread waits on now, so a token minted before an edit cannot be used at all |

## Numbers

With the first, two-statement append, the mailbox measurement rose from 31.8 to 57.1 SQLAlchemy statements per
message. The append is now one statement (an INSERT that reads the next `seq`); the measurement has not been rerun.

## Gotchas

| Gotcha | Consequence |
|---|---|
| SQLite's single shared connection | A stream-side write interleaved with a node's usage write and lost it; on SQLite the log is written at run end |
| `follow` streams never end | The ASGI test transport buffers them; tests use `follow=false` or iterate the generator |
| Reviews of chat-agent graph threads | Decide serves them too (`get_review` builds any thread's review); the Reviews list still hides chat threads |
| Experiments E1 to E3 and `prove-graphs.py` | Still resume on the run stream and now get 409; they are records of their run, not kept current |

## Feeds

`docs/architecture/api.md` (event schema, re-attach, team stream, decide) and `durability-failure-and-audit.md`
(journal and event storage); hunks sent to the docs owner. Next: chat on the graph calls.
