# Service test speed and pruning

Status: current. Where each service suite spends its time, what was changed in the test rig to make it faster, and
every test deleted for being redundant, with the test that still covers it.

## Where the time goes (measured 2026-11-16)

Each figure is one `make -s test PKG=services/<svc>` run, on a machine with 14 cores and a load average of 6 to 8 from
other builders' suites.

| Service | Tests | Wall clock | Main cost |
|---|---|---|---|
| agents-service | 1,871 | 724 s | CPU in the test process: each test starts its own app, and FastAPI builds a route's dependants and pydantic fields on the first request to it (about 0.2 to 0.5 s per app). Profiled on four API files, 26 of 35 s went to `fastapi.utils.create_model_field`. |

What it is not, for agents-service: emptying the 58 tables before a test takes 25 to 65 ms; starting the app's
lifespan (seeding) takes about 70 ms; `create_app` itself takes 8 ms; the schema is migrated once per run, not per test.
Real sleeps (timer, lease and mail tests) add about 60 to 70 s in total; they are left as they are, since those files
are lease and timer conformance tests that builders are editing.

The cost is per test and CPU-bound, so it divides across processes: the fix is a parallel run with one database per
worker, below.

## Parallel runs

`make -s test PKG=services/<svc> PAR=<n>` runs the suite on n pytest-xdist workers. `scripts/test_db.py --workers n`
migrates the run's test database once and copies it per worker (`<name>_gw0` …), and each worker's conftest points
itself at its copy (`ops_service_kit.testdb.use_worker_database`), which leaves the live-database guard's pair untouched.
A whole test file runs on one worker. A suite runs in parallel only once it is listed in `PAR_SUITES` (make/env.mk),
after three parallel runs in a row with no failure that a serial run does not also have; any other suite refuses `PAR=`.
CI shards are unchanged: a shard runs serially.

| Service | Serial | PAR=5 (three runs) | Failures in every run, serial and parallel alike |
|---|---|---|---|
| agents-service | 724 s | 178, 180, 173 s | `test_tools_ownership.py::test_tools_chain_adopts_tables_the_agents_chain_created` (also red in the serial baseline); three in `test_workflow_tools.py` and `test_child_runs.py` from source edits in progress on the branch |

## Deleted tests

| Test | Reason | Surviving cover |
|---|---|---|
