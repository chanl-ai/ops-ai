# A paused thread survives a graph change

Status: E1, holds, 2026-10-10. Threads pin the graph version they started on; in-process, deterministic model calls.
Tests: `services/agents-service/tests/api/test_graph_versions.py`. Script:
`services/agents-service/experiments/e1_pause_survives_graph_change.py` (no model calls).

## Verdict

A thread paused on v1 and resumed after v2 and v3 were published finishes on v1's graph, new threads start on the
latest version, and a paused thread moves between versions only when its waiting node exists by name in the target.
Without the pin, a graph edit silently changes a case's path or silently drops its pending decision.

## What holds

| Failure mode | Result |
|---|---|
| Paused v1 thread resumes on a newer graph | holds: every visit tagged `@v1`, old node names `grade` and `human` used |
| New thread starts on an old version | holds: starts on latest, visits tagged `@v2` |
| Migrate to a version without the waiting node | holds: 409 `node_missing` |
| Migrate a thread that is not waiting on an interrupt | holds: 409 `not_waiting` |
| Stored definition changed under a pinned thread | holds: run refused on digest mismatch |
| No pin, paused node kept (v2) | fails: resume continues on v2 with nothing recording the switch |
| No pin, paused node renamed (v3) | fails: `next=()`, no interrupt, no error, no reply, `status=None` |

`graph_threads.version` and `.digest` pin a thread (migration `0003_graph_versions`); every run, resume and state read
compiles the pinned version from stored JSON, cached by digest. `POST /v1/threads/{id}/migrate {toVersion}` moves a
waiting thread.

## Numbers

50 compiles per version, in-process:

| Measure | Value |
|---|---|
| Compile, no cache | v1 2.64 ms median (2.96 max), v2 2.91 ms median (3.50 max) |
| Cache hit, including parsing and hashing stored JSON | 0.056 ms; 1001 gets compiled once |
| Storage | One row per published version; two columns per thread |

## Gotchas

| Gotcha | Handling |
|---|---|
| LangGraph raises no error when a thread resumes on a changed graph | Resume only on the pinned version |
| A pin test passes with the pin removed when every edit sits upstream of the pause | Test asserts the `@v1` tag; with the pin removed it fails with `['classify@v1', …, 'human@v2', …]` |
| Migrate checks node names only; a changed `human`, or a changed path after it, applies to a migrated case | Migration review should diff definitions from the pending node onward |
| Digest is SHA-256 of canonical JSON without the version number | No cache invalidation: a digest names one definition forever |
| Every pinned version stays compiled while any of its threads can resume | Retire a version only when no thread pins it, or after migrating those threads |

## What is left, and what it feeds

| Item | Feeds |
|---|---|
| Definition diff from the pending node onward | Safe migration review |
| Version retirement once no thread pins it | Process memory over long pauses |
