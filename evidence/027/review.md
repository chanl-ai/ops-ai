# c-027 independent review

One entry per commit, by a reviewer that did not build it. Each check ran on a clean `git archive` export of the
commit against a private database (`ops_review_c027`); the working tree was never edited. Probes ran as extra tests
in that export only, through the real routes, the real executor and the in-process fake bank (`/v1/echo-headers`
repeats the request's headers, as a careless upstream would). Zero real model calls.

## 7aec37d: edit an operation's HTTP call (API slice)

- Check: tools-service `make verify` on the export: lint and pyright clean, 61 passed, OpenAPI 35 operations, 3
  untyped on the allowlist.
- Probes that held: a literal credential in an edited header is 400 and nothing is staged; an edited URL off the
  module endpoint is 400 on edit and on add, and http is refused; method, path and body stage as major (2.0.0 with a
  Security review), headers, transform and timeout as minor; a pending edit is not called until published; a
  transform that throws (undefined field, `__class__.__mro__`, `cycler.__init__.__globals__`) returns the masked
  answer with `transform_error`; on that failure path a reflected vault secret comes back as `[secret]`; timeout
  999 and 120001 ms are 400, 1000 and 120000 ms accepted, a slow upstream answers `TIMEOUT`.
- Verdict: reject.
- Defect 1 (probed): a transform can carry a vault secret out encoded. `scrub` runs after the render and replaces
  only the literal secret, so with an operation header `X-Api-Key: {{SECRET}}` against an upstream that repeats it:
  `{"k": "{{ data.headers["x-api-key"] | reverse }}"}` returned `a6b5c4d3e2f1-knab-ks` (the secret reversed), and
  `{{ data.headers["x-api-key"] | list | join(" ") }}` returned it spaced. The error path leaks the same way:
  `{{ data[data.headers["x-api-key"] | reverse] }}` put the reversed secret in `transform_error`. Headers and
  transform are minor changes, so no Security review stands between a builder and this. Fix: scrub the masked
  response before rendering as well as after, so the template only ever sees `[secret]`; keep the probe as a test.
- Defect 2 (measured): the render runs synchronously inside the async executor with no time limit. The sandbox caps
  one `range()` at 100000 but not nesting: 3e7 loop iterations took 0.4 s and 3e8 took 5.1 s, so
  `{% for a in range(100000) %}{% for b in range(100000) %}{% endfor %}{% endfor %}` would hold the gateway's event
  loop for minutes, stalling every tenant's calls. Fix: render off the event loop with a time budget (an
  over-budget render is a `transform_error`), or count loop iterations in the environment and stop at a cap.

## d35ba96: the transform sees no secret and cannot run away

- Check: tools-service `make verify` on the export: lint and pyright clean, 63 passed, OpenAPI 35 operations.
- Probes that held: 7aec37d's three encodings now return `]terces[`, `[ s e c r e t ]` and an error naming
  `]terces[`, the secret never; the failure path returns `[secret]`; nested `range(100000)` is refused by the
  10000-item budget at once; `lipsum(100000)` stops at the 1 s deadline.
- Verdict: reject.
- Defect (measured, each in its own process): the deadline is a trace function, which runs between Python-level
  events, so a single C-level allocation is never interrupted, and `MAX_RENDERED` is checked only after the string
  exists. `{{ "a"|center(300000000) }}` peaked at 1.5 GB before stopping at 1.68 s; `{{ "%300000000s"|format(1) }}`
  1.5 GB; seven chained `replace("a","aaaaaaaaaa")` 543 MB. Memory grows with the width, so `center(3000000000)` asks
  for over 10 GB in one call and can take the gateway process down for every tenant (not run on the shared machine).
  Fix: bound the size before the allocation, not after: wrap or drop the filters that take a size or grow a string
  (`center`, `indent`, `wordwrap`, `format`, `truncate`, and `replace`, refused when its result would pass
  MAX_SIZE), with these three as tests.

## be91730: edit the HTTP call in the console's operation sheet

- Check: on a clean export of be91730, `make console-verify` (tsc and check-standards, 546 files clean),
  check-docs clean, and `make usecase-test UC=uc-010 LAYER=ui` 9 checks against the real tools-service.
- Read: the sheet reuses `HttpOperationBuilder` through `callOnly`, not a fork; the URL check compares against
  `${base}/`, so `https://bank.test.evil` is refused, not just a different path; timeout outside 1 to 120 s disables
  Stage; only changed fields go in the PATCH, and the service validates them again (7aec37d's probes).
- Verdict: accept.
- Notes: after staging, the sheet header and the operations table show the staged path while calls still run the
  published one (screenshot 2), so the page reads as if the edit were live; label staged values or show the
  published call beside them. The commit also carries a `packages/usecase-runner/src/harness.ts` cleanup change its
  body does not name.

## fca4b6b: every string is sized before it is built

- Check: tools-service `make verify` on the export: lint and pyright clean, 63 passed.
- Probes that held: `"a".ljust(10**9)` and `"%300000000s" % 1` are refused before allocating (peak 30 MB);
  d35ba96's center, format and replace probes are tests that fail without the checks.
- Verdict: reject.
- Defect (measured): concatenation is not sized. A `namespace()` value doubled in a loop stays inside the range
  budget and the deadline: `{% set ns = namespace(s="a") %}{% for i in range(27) %}{% set ns.s = ns.s ~ ns.s %}
  {% endfor %}{{ ns.s|length }}` built 134,217,728 characters (peak 309 MB) in 0.04 s and rendered only the length,
  so the output cap never applied; `+` did the same, and a list doubled 24 times held 16,777,216 items. Six more
  iterations ask for 8 GB faster than the 1 s deadline can act.
- Recommendation: two rounds have closed paths one at a time (filters, then str methods and `%`) and the third is
  open. Bound the process instead of the operators: render in a child process with an address-space limit
  (`resource.setrlimit(RLIMIT_AS)` on Linux, where the gateway runs) and a hard kill at the deadline, so any
  allocation or loop ends as a `transform_error` without touching the gateway. Keep the operator checks as fast
  refusals and add the doubling probe as a test.

## 4104f51: render a response transform in a watched child process

- Check: tools-service `make verify` on the export: lint and pyright clean, 63 passed (the builder reported 71,
  likely counted in a tree with later tests).
- Probes (from a script file; forkserver children import the parent's `__main__`, so a stdin-run probe fails, and
  `ops_tools/__main__.py` is guarded by `if __name__ == "__main__"`, so `python -m ops_tools` is safe):
  fca4b6b's `~` doubling and `+` doubling at 33 iterations and list doubling at 30 are stopped as out of memory in
  0.07 to 0.17 s with the parent at 34 MB; `center(300000000)` is refused before allocating; a 10000-iteration
  `lipsum` loop is stopped at 1.01 s; a normal transform takes 0.01 s and 50 concurrent ones 0.07 s, all correct.
- Verdict: accept. The process bound closes every allocation and loop path the operator checks left open.
- Notes: on macOS the memory bound is the 20 ms poll, as the builder says; on the Linux gateway `RLIMIT_AS` backs it.
  Each render costs a fork; at high call rates measure it before relying on transforms in hot paths.

## 3d0fb8f, 7d87af0, 32f17b3, ffcf7a9, 584d20b, cf82997, e9444ec, 8535924: labels, uc-010 api, docs, picker fix, evidence

- Check: on a clean export of 4bff2f6, `make console-verify` clean (547 files), `make usecase-test UC=uc-010 LAYER=api`
  19 checks and `LAYER=ui` 10 checks, both against the real tools-service.
- walk repeated: the live walk's last step, publishing the staged path edit -> GET
  http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200 shows v1.0.0, get_statement at GET /v2/statements/latest,
  a security review pending and nothing staged, as the walk recorded.
- 3d0fb8f: accept. The sheet header and the operations table label a staged call as not yet what calls run, which
  closes be91730's note 1; its body names be91730's harness cleanup (note 2); uc-010 ui checks the label.
- 7d87af0: accept. uc-010 api drives an edited call through /v1/calls against the https fake bank, including a slow
  path for the per-operation timeout.
- 32f17b3: accept. The overview and the use-case page describe edit, transform and timeout as built; one
  `usecases/027/*.yaml` per acceptance line.
- ffcf7a9: accept. The test panel falls back to the first operation when its choice is gone, the gap the owner's walk
  found; a four-line effect with a stated reason.
- 584d20b, cf82997: accept. Evidence only; the walk's state matches the live module above.
- e9444ec: accept. uc-010 expects c-038's `UPSTREAM_TIMEOUT` for a slow upstream, the code d652d06 introduced.
- 8535924: accept. The expected stdout matches the runner's padded `uc-010 ui   10` line.

## Card verdict

Every c-027 commit has a verdict above. 7aec37d, d35ba96 and fca4b6b were rejected, and their defects are closed by
d35ba96 (pre-render scrub), fca4b6b (sized strings) and 4104f51 (a watched child process per render), each probed on a
clean export; be91730's two notes are closed by 3d0fb8f. Every other commit is accepted.

walk repeated: the builder's last walk step, publishing the staged path edit -> mod_6857637c8ee9 at v1.0.0 with
get_statement on GET /v2/statements/latest, a security review pending and nothing staged, GET
http://localhost:8720/v1/tool-modules/mod_6857637c8ee9 200

verdict: approve
