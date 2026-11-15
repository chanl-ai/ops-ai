# Standards: tests

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `TS1` to `TS8` are frozen.
The repository's test rules are in `CLAUDE.md` "Tests", `.claude/agent-rules.md` and `docs/usecases/README.md`.

A test exists for a named failure mode, has been seen failing once, asserts through a public seam, and runs on a
throwaway database with a scripted model. The suite holds or shrinks when a change lands.

## TS1 Name the failure modes, then one test each

Rule: before writing a test, list the ways the change can break in production; write one test per failure mode and
stop.
Why: a named failure mode is what a test protects against; coverage counts lines that ran and misses wrong answers.

Pattern (`scripts/check_downgrades.py:1`): the docstring names the failure (an empty downgrade leaves columns behind
and the second upgrade fails), the day it happened and the check that stops it.

Check: `scripts/agents/test_audit.py` lists failure modes in the design with no test (`make agent-test-audit`).

## TS2 A budget per change

Rule: a change adds at most 5 tests when small, 10 when medium and 15 when large; more needs a written reason; when a
file is touched, its tests that repeat a check or test a library are deleted.
Why: every test costs run time and upkeep on every later change.

Check: no check yet. Needed: a script that counts new test functions in a change against the budget on the card.

## TS3 Every new test is seen failing once

Rule: each new test is run with the fix reverted, fails for the stated reason, and that failure is quoted in the
evidence.
Why: a test that has never failed may test nothing.

Pattern (`.claude/agent-rules.md`, "Done means"): the first failure of each new test is part of the hand-back.

Check: `scripts/agents/test_audit.py` (mutation score on changed lines; a surviving mutant is a test that cannot fail).

## TS4 Assert through the public seam

Rule: a test asserts what a caller sees (a route through the real app, an SDK call, a screen); fakes sit only at the
edge (network, clock, model, outside APIs); private helpers, call order and internal shapes are never asserted.
Why: a test on a private helper breaks on every refactor and misses the wiring, which is where bugs survive.

Pattern (`packages/ops_store/tests/test_isolation_sites.py:1`): the test reads the source tree and asserts the
behaviour every caller depends on (every widening has a reason) rather than any function's internals.

Check: review, with `test_audit.py` smells (assertion-free, tautological, mystery-guest).

## TS5 A use case per layer

Rule: each user-visible behaviour has a use case per layer it touches (`api`, `sdk`, `cli`, `ui`) that prints `PASS` or
`FAIL` per check and runs through `make usecase-test`.
Why: a unit test proves one function; the use case proves the behaviour a person sees, through the real seams.

Pattern (`docs/usecases/README.md`): the registry, the `test-uc-NNN-<layer>` scripts and "a pass needs evidence".

Check: `make usecase-test UC=<id> LAYER=<layer>`; `scripts/agents/affected_usecases.py` names the ones a change
touches (`make uc-impacted`).

## TS6 Scripted model, throwaway database, both databases

Rule: tests and use cases run on the scripted model with model keys removed, on a database made for the run
(`scripts/test_db.py`); store tests run on PostgreSQL and SQL Server.
Why: the same answer every run, at no cost, on both supported databases.

Pattern (`make/python.mk`): `make verify` unsets the model keys; `make test` makes the database.

Check: `make/python.mk`; `scripts/test_db.py`; `make uc-sql-server` for the SQL Server run. Needed: a SQL Server run of
every store suite in CI.

## TS7 Tests and code by different hands

Rule: the test designer commits failing tests and changes no product code; the builder changes no test file after that
commit; a test the builder thinks is wrong goes back through the tracker.
Why: a second author tests the cases the coder did not think of.

Check: `python scripts/agents/tests_untouched.py <tests-commit>`.

## TS8 No test of a library

Rule: no test asserts a third-party library's behaviour: no schema-identity checks, no serializer shape checks, no
"does the constructor construct".
Why: upgrading a library should not mean repairing tests that never protected us.

Check: review; `test_audit.py` duplicates.
