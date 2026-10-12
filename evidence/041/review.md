# c-041 independent review

One entry per commit, by a reviewer that did not build it. Checks ran on a clean `git archive` export of HEAD 78e1f20
against a private database; the working tree was never edited. Probes ran as extra tests in that export only, through
the real routes, the real gateway and the in-process fake bank. Zero real model calls.

## 0585ac3: a module's calls, error rate and p95 come from the call log

- Check: tools-service `make verify` on the export: lint and pyright clean, 101 passed. No `seed_*` traffic field is
  left in tools-service's code, seed or the console's mock.
- Read: one GROUPING SETS aggregate over `gateway_calls` with outcome `ok` or `error`; the module's p95 comes from the
  `(module_id)` set, so it is over all the module's calls. `created_at` and the window bound are both written by
  `isoformat(timespec="milliseconds")` with `Z` (`now_iso`, `_since`), and `app.py:235` is the only writer, so the text
  comparison holds.
- Probes that held: a new blank module reads 0 calls, 0 errors, 0 p95 on its page and in the list, 14 activity days
  from 2026-09-29 to 2026-10-12 all zero, 0 denied. Two reads, one upstream failure and one refused write gave the module
  4 calls, error rate 0.25, today 4 with 1 error, and denied 1; the refused write counted no call. An approved write sent
  twice under one key ran once and replayed once: its operation shows 1 call.
- Defect against the spec's metric ("Calls · 24h matches `/v1/executions` for the same day"): `/v1/executions` maps a
  replay to status `ok` and an `in_progress` refusal (409, the same write already running) to `error`
  (`modules/executions.py:10`), while the counts leave both out. In the probe, the replayed write listed two `ok` rows
  under an operation that counts 1 call. On the Activity tab the executions table sits under the counters, so the two
  disagree with nothing on the row saying why. Either the executions status names a replay as a replay and a 409 as
  refused, or the metric is restated; the spec decides.
- Verdict: changes requested.

## 5a96f8f: an approval is expiring in its last 7 days, not its last 30

- uc-042 checks both sides: a 30-day approval granted today is approved, one with five days left makes the module
  expiring.
- Verdict: accept.

## 9fda966: uc-042 counts a module's traffic from calls made through /v1/calls

- `make usecase-test UC=uc-042 LAYER=api` on the export: 9 checks passed.
- Verdict: accept.

## 2e0305d: traffic comes from the call log; the acceptance maps to uc-042

- check-docs passes; the overview row matches 0585ac3.
- Verdict: accept.

## b5a0c3e: the activity chart stays at zero on days without calls

- Console `pnpm verify` on the export: exit 0.
- Verdict: accept.

## Card

walk repeated: on the builder's `make up ISOLATED=1 AUTH=platform` stack, module mod_aef7b3232e4e read 4 calls, error
rate 0.25, today 4 with 1 error (GET :9720/v1/tool-modules/mod_aef7b3232e4e 200); one more read through
POST :9720/v1/calls (echo_get_tpj6, a real call to postman-echo.com) 200 ok -> the module read 5 calls, error rate 0.2,
today 5 with 1 error, echo_get_tpj6 at 4 (GET :9720/v1/tool-modules/mod_aef7b3232e4e 200).

verdict: changes requested (0585ac3: the executions log lists replays as ok and 409 in-progress refusals as errors,
which the counts exclude, so the card's metric does not hold once a write is replayed).
