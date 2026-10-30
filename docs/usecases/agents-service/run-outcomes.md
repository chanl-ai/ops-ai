# Every workflow run ends with a clear outcome

Status: current. Id: `uc-567`. Service: `agents-service`. Layers: api, ui.
Card: an earlier change.

A workflow run either finishes, fails with a reason, or shows as Stuck with the reason and Retry and Cancel. A write
step whose result is uncertain fails the run at once and is never sent again; an outage of tools-service is retried
until it is back; a run nothing is working on is marked Stuck by the reconciler, and Retry carries it on from its last
recorded step without sending a recorded write twice. Human Tasks lists every waiting run, and an email whose run will
not start is set aside so the mail after it is read, with Run again on its row.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A run whose worker dies on it every time is marked Stuck with the reason and no worker takes it again | ui | 1 | 1 |
| S2 | The run page shows Stuck with its reason, Retry and Cancel, at 1280 and 375 px | ui | 3-4 | 4 |
| S3 | A Retry the run has moved past is refused on the page, and Retry from the page carries the run to its end | ui | 5-6 | 6 |
| S4 | An email whose run will not start is set aside so the mail after it is read, and Run again on Activity starts it | ui | 7-8 | 8 |
| S5 | A write whose answer never came fails the run at once with the reason and is sent once | api | 11 | 11 |
| S6 | A run meeting a tools-service outage waits and finishes once it is back | api | 12 | 12 |
| S7 | A run whose worker keeps dying is Stuck, and Retry carries it on without writing twice | api | 13 | 13 |
| S8 | Human Tasks lists a waiting run older than the newest 200 | api | 14 | 14 |
| S9 | A set-aside email is run again once, and its kept copy is gone after | api | 15 | 15 |

## Preconditions

| Needs | How |
|---|---|
| The demo stack: agents-, tools- and platform-service, the console, the core bank fake and its module | `withUiStack(..., { demo: true })` |
| Workers the walk starts and lets die | `stack.startWorker` with the dev and test only `OPS_ENGINE_FAULT_KILL_AFTER_NODE` and `OPS_ENGINE_FAULT_IGNORE_RECORDED`, and a 2 s lease |
| A reconciler pass every 2 s | `OPS_ENGINE_RECONCILE_SECONDS=2` on the worker that stays up |
| A mailbox | GreenMail through tools-service (`tools: { mail: true }`); mail sent to it by SMTP |
| An email whose run will not start | The dev and test only `OPS_EMAIL_FAULT_FAIL_SUBJECT` on the worker that reads the mailbox: a subject containing it fails the start |
| People | James Richardson (team_ops builder), Sam Adeyemi (Security admin: the mailbox secret and mail hosts) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| setup | James saves the `uc561ui_customer_check` workflow: Request, then Look up the customer (`get_customer`, a read), then Found | Saved (201) |
| 1 | James starts a test run; 7 workers in turn take it and die by SIGKILL on the lookup; an 8th worker starts | The 8th worker does not take the run; within seconds it reads `stuck`, its reason says the worker stopped 6 times, and `canRetry` is true |
| 3 | James opens the run page at 1280 px | The status pill reads Stuck; the reason is on the page; Retry and Cancel are in the header; nothing says the run failed |
| 4 | The same page at 375 px | No sideways scroll; Retry is on screen |
| 5 | The run is retried elsewhere (no worker is running, so it stays queued); James presses Retry on the page he had open | The page says the retry could not be done and why; the run is not changed by his press |
| 6 | A second run is made Stuck the same way; James presses Retry on its page with a worker running | The run goes on from the lookup to Found and the Retry button goes |
| 7 | Sam stores the mailbox secret and allows the mail host; James connects the mailbox and publishes `uc567mail_<run>` on it; two emails arrive, the first with the failing subject | The first email's start fails on 2 reads (`start_failed`), then it is set aside (`set_aside`) with its reason; the second email starts its run |
| 8 | James opens Activity, presses Run again on the set-aside row and confirms | The dialog asks first; after Confirm the page says the run started, and the run reads `succeeded` |
| 11 | (api, a test run) A note write whose mock answer is a timeout: the call left tools-service and no answer came | The run fails at once; its error says the write may have run; Executions shows one call, failed |
| 12 | (api) tools-service stops; a run's lookup meets the outage; tools-service starts again 3 s later | The run waits (queued or running) and then ends at Found |
| 13 | (api) A run writes a note, then 7 workers in turn die on its lookup; an 8th worker with a 2 s reconciler starts; Retry | Stuck with "stopped 6 times"; after Retry it ends at Found and the bank has its note once |
| 14 | (api) One run waits on a person, then 200 newer runs of the workflow start | Human Tasks lists the first run's task |
| 15 | (api) Two emails to a GreenMail mailbox, the first with the failing subject; then Run again on the set-aside one, twice | 2 `start_failed` then `set_aside` for the first, `started` for the second; Run again answers 202, then 404 |
