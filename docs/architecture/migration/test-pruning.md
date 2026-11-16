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
worker.

## Deleted tests

| Test | Reason | Surviving cover |
|---|---|---|
