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
  `cli` needs `scripts/sample_team.py`.
- A ui script fails when a page it opens reads data the console still answers from its mock beside real services:
  the console writes `[ops-ai sample data] <area> on <path>` (`apps/console/src/lib/api/sample-reads.ts`) and the
  harness's `chromium` turns it into a `FAIL`. A script that means to show sample data calls
  `expectSampleData('<path>')` first. Reads the app shell makes on every page (`on *`) are not a page's failure.
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
- [docs/usecases/README.md](../../docs/usecases/README.md): the registry and the rules every use case follows

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [tests](../../docs/architecture/standards/testing.md) (`TS1` to `TS8`), [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.

## Known traps

- A use case needs the plugins checkout, a standing `make up` stack or a real provider key and a hosted runner has none => say so in its registry status (`needs-plugins`, `manual`, `needs-key`; `make checks` runs `scripts/check_usecase_needs.py`) or start the need from the script
- A hosted runner reaches PostgreSQL at `localhost:5477`, not the devcontainer's `postgres:5432` => take host and port from `OPS_DATABASE_URL` (`pgUrl` in `isolation.ts`), never a fixed name
- Scan fixtures read through OCR fail on a runner without tesseract => the usecases job installs `tesseract-ocr`; a script that needs another binary installs it in the job, not in the script
- A test of a two-person rule passes only with `requesterMayDecide` off, and it defaults on => set it in the test (`twoPersonRuleOn()` in `docs/usecases/lib/workflow_ui.mjs`, or the policy route), never rely on the default
