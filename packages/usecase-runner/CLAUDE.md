# usecase-runner: working rules

Status: current.

`@ops-ai/usecase-runner`, the one TypeScript package here. It runs the use cases in `docs/usecases/`: parses the
registry table, resolves a use case and layer to its script, runs it on ports and a database the run owns, and decides
PASS or FAIL from the script's output and exit code. It also holds the harness the Node (ui) scripts import:
Playwright's `chromium`, `check`, and `withUiStack`, which starts the services on the scripted model and a console
build pointed at them. Package rules: [../CLAUDE.md](../CLAUDE.md); repo-wide rules:
[../../CLAUDE.md](../../CLAUDE.md#folder-guides). Module table and exit codes:
[docs/packages/usecase-runner/overview.md](../../docs/packages/usecase-runner/overview.md).

## Contract with callers

- A script passes only when it exits 0, prints no `FAIL <name>: <detail>` line and prints at least one `PASS <name>`
  line, so a script whose assertions never ran cannot pass.
- The registry parser reads the table in `docs/usecases/README.md` by its header (Id, Service, Title, Layers, Status);
  an unknown layer, a duplicate or a malformed id stops the run with exit 2.
- Each run picks free ports and creates its own database (`isolation.ts`), dropped at the end; `OPS_USECASE_*` set by
  the caller pins one. Model keys are removed from a script's environment unless `APPROVED_REAL_CALLS=<n>` is set.
- A layer is available when its provider exists (`src/layers.ts:12`): `sdk` needs `sdk/python` or `sdk/typescript`,
  `cli` needs `scripts/sample_team.py` or `packages/ops_plugins`.
- Screenshots and logs go under `evidenceDir(...)`: `OPS_EVIDENCE_DIR`, else `.logs/usecases/`, which git ignores.
- UI scripts run headless Chromium against a production console build cached per source hash
  (`src/console-build.ts`); `OPS_USECASE_CONSOLE=dev` runs `next dev` instead.

Called by `scripts/usecase.mjs` and every `docs/usecases/*/scripts/*.mjs` script.

## Run and test

| Task | Command |
|---|---|
| Type-check and the runner's own tests (about 25 s) | `make usecase-runner-test`, or `pnpm --filter @ops-ai/usecase-runner verify` |
| Tests only, from this folder | `pnpm test` |
| Types only, from this folder | `pnpm typecheck` |
| Run a use case through the runner | `make usecase-test UC=uc-021 LAYER=api` |
| Registry, one entry, coverage | `make usecase-list`, `make usecase-show UC=<id>`, `make usecase-coverage SERVICE=<service>` |

A change here is skipped by `scripts/verify-changed.sh` (`packages/usecase-runner/*` is matched and ignored), so run
`make usecase-runner-test` yourself before committing.

## Reference docs

- [docs/packages/usecase-runner/overview.md](../../docs/packages/usecase-runner/overview.md): modules, verdict and exit codes.
  Its layers row says `sdk` needs `packages/sdk-py` or `packages/sdk-ts` and `cli` needs `packages/ops-cli`; the code
  checks `sdk/python`, `sdk/typescript`, `scripts/sample_team.py` and `packages/ops_plugins`, so that row is out of date
- [docs/usecases/README.md](../../docs/usecases/README.md): the registry and the rules every use case follows
