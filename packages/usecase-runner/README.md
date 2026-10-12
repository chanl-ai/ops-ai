# @ops-ai/usecase-runner

Runs the use cases in `docs/usecases/`: resolves a use case and layer to its script, runs it, prints PASS or FAIL per
check, and exits non-zero on failure. Design and exit codes: `docs/packages/usecase-runner/overview.md`.

```bash
make usecase-test UC=uc-001 LAYER=api     # or: node scripts/usecase.mjs test --uc uc-001 --layer api
make usecase-coverage SERVICE=agents-service
make usecase-runner-test                  # this package's own tests
```
