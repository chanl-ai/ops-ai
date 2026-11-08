# Ops AI console: working rules

Status: current.

Ops AI is the operations console for a bank's AI agents (demo tenant: Harbor & Pine Bank). These rules are
enforced by `pnpm verify` (type-check, the embed app's type-check, since it draws these chat components through its own `@/lib/api`, and `scripts/check-standards.mjs`), which the pre-commit hook runs.
A rule that is not checked by the script is still a rule; the script covers the ones a grep can prove.

This app runs Next.js 16 (`next` 16.4.1), whose APIs and file conventions differ from older releases; read the notes in
@AGENTS.md and the matching guide in `node_modules/next/dist/docs/` before writing Next.js code. Rules shared with every
other folder (onion order, one stack, calling the API as a person, tests, commits) are in
[Working in one folder](../../CLAUDE.md#working-in-one-folder).

## Run and check from this folder

| Task | Command (in `apps/console/`) |
|---|---|
| The console on the live stack | `make up` from the root serves it at http://localhost:3016 with every area on the services; `make -C ../.. logs SVC=console FOLLOW=0` prints its log |
| The console on the mock alone | `pnpm dev` (:3016) or `pnpm dev:runtime` (:3017, chat on the agents service); not while `make up` holds the port |
| Type-check | `pnpm typecheck` |
| Standards check | `pnpm check:standards` (`scripts/check-standards.mjs`; `--write-baseline` locks in a drop it reports) |
| Unit tests | `pnpm test` (`node --test 'src/**/*.test.ts'`, beside the code they test under `src/lib/`) |
| All of the above, plus the embed app's type-check | `pnpm verify` |
| Production build | `pnpm build` |
| Make verbs | `make help`: `install`, `run`, `lint`, `typecheck`, `verify`, `stop`, `logs`, `health`, `clean`. `make test` prints "no tests yet" and runs nothing; use `pnpm test` |

The console type-checks against the TypeScript SDK's build in `sdk/typescript/dist/`, made by `pnpm install`. After a
route change regenerates the SDK (`make openapi`), rebuild it with `pnpm --filter @chanl-ai/ops-ai build` (or
`make sdk-verify`, which builds it as part of its test); until then `tsc` reports fields the services already return as
missing (TS2339).

## Checking a screen in a browser

Check every changed route headless with Playwright before calling the change done. `chromium` comes from
`@ops-ai/usecase-runner/harness`, which resolves from the repo root.

| Check | How |
|---|---|
| Against the live stack | A scratch Node script run from the repo root: open http://localhost:3016/login, sign in as a seeded person (their emails are in `services/platform-service/seed/people.json`; the dev password is `platform_demo_password` in `packages/ops_service_kit/src/ops_service_kit/settings.py:287`), visit the route, collect `pageerror` events and take a screenshot at 1440 and 390 wide |
| As a repeatable check | A ui use case: `docs/usecases/<service>/scripts/test-uc-NNN-ui.mjs` with `withUiStack` and `chromium` from the harness (example: `docs/usecases/console/scripts/test-uc-047-ui.mjs`), run with `make usecase-test UC=<id> LAYER=ui` |
| Loading, error and empty states | On the mock (`pnpm dev`), add `?mock=slow`, `?mock=error` or `?mock=empty` to the route |
| Developer pages | `/dev/*` (the widget gallery and others) answer only under `next dev` or with `OPS_ALLOW_PREVIEW_PAGES=1` (`src/proxy.ts:10`) |

Before the browser, call the routes the screen uses as the same person: `make api GET <path> AS=<role> SVC=<service>`,
or the area's own targets (`chat`, `kb-*`, `apps-*`, `tools-*`, `runs-*`, `tasks-*`, `memories-*`), never an ad-hoc
script or SQL; `make test-data-clean` removes what they made ([make/CLAUDE.md](../../make/CLAUDE.md)). A screen that shows the wrong data
because the route returns it is fixed in the service, never in the hook or component.

## Where things live

| Path | Holds |
|---|---|
| `src/app/` | Routes (App Router); `(auth)` holds sign-in, `_shell` the signed-in frame, `dev` the developer pages |
| `src/components/ui/` | shadcn primitives (`components.json`: style `new-york`, registries `@ai-elements` and `@shadcnblocks`); never edited |
| `src/components/shared/` | The app's own building blocks over the primitives (`PageLayout`, `DialogShell`, `FormField`, `FileUpload`, `DeleteDialog` and the rest of the Components table below) |
| `src/components/<area>/` | One folder per console area |
| `src/hooks/` | Data hooks (`<area>-queries.ts`) |
| `src/lib/api/` | `contract.ts` (`OpsApi`), `<area>-contract.ts` and `<area>-http.ts` per area, `ops-sdk.ts` for screens on the generated SDK, `index.ts` (the only env reader), `mock/` (the only fixtures) |
| `src/lib/types/` | Shared types |
| `scripts/` | `check-standards.mjs` with its baselines, `bake-workflow-positions.ts` (`pnpm bake:workflows`) |

## Reference docs

| Topic | Doc |
|---|---|
| Every page and what it shows | [docs/console/page-plan.md](../../docs/console/page-plan.md) |
| Settings tree, chat, agents and workflows | [docs/console/](../../docs/console/) |
| Product designs by area | [docs/design/](../../docs/design/) |
| Use cases the console must pass | [docs/usecases/README.md](../../docs/usecases/README.md) (rows with service `console`) |
| The SDK screens move onto | [docs/sdk/](../../docs/sdk/), [sdk/CLAUDE.md](../../sdk/CLAUDE.md) |

A `feat` or `fix` that changes this folder needs a What's new entry ([Commits](../../CLAUDE.md#commits)).

## Layers (one direction only)

| Layer | Path | May import | Must not |
| --- | --- | --- | --- |
| Types | `src/lib/types/` | nothing app-level | contain data |
| API contract + clients | `src/lib/api/` | types | be imported by components |
| Mock (the only fixtures) | `src/lib/api/mock/` | types, contract | be imported outside `src/lib/api/` |
| Hooks | `src/hooks/` | api, types | render UI |
| Components | `src/components/` | types (type-only), other components, hooks for local UI state | fetch data or import `@/lib/api` values |
| Pages | `src/app/` | components, hooks, types | define fixtures or call `api` directly |

- Every value a screen shows comes from a hook backed by `OpsApi` (`src/lib/api/contract.ts`). Adding data means: type → contract → `http.ts` → mock → hook.
- Counts, totals and stats are computed by the API, never aggregated in a component.
- A screen that moves to a real service calls it through the generated SDK (`@chanl-ai/ops-ai`, a workspace package built on `pnpm install`): a hook runs `sdk((ops) => ops.raw.<service>.<operation>(...))` from `src/lib/api/ops-sdk.ts`, which sends through `fetchWithIdentity` (token, team, one renew) and turns refusals into `ApiError`. Types come from the SDK (`OpsAI['raw'][service]`), not hand-written copies. Example: `src/hooks/systems-queries.ts`. The area clients (`*-http.ts`) stay until their screens move.
- `NEXT_PUBLIC_OPS_API_URL` set → every area uses the real HTTP client; unset → mock. `NEXT_PUBLIC_OPS_CHAT_API_URL` set → `api.chat` uses HTTP to that service (the Runtime) and every other area stays as above (`pnpm dev:runtime`). `NEXT_PUBLIC_OPS_CASES_API_URL` set → `api.cases.runs`/`run` and `api.reviews` use the agents service the same way. `NEXT_PUBLIC_AUTH_PROVIDER` picks the sign-in adapter. Only `src/lib/api/index.ts` reads env.

## Components (reuse before writing)

| Need | Use | Never |
| --- | --- | --- |
| Page header | `PageLayout` (icon, title, one-line description, actions, `backHref` on record pages) | hand-built headers |
| Switch between a section's pages | `TitleSwitcher` via `PageLayout` `switcher` (pages from `sectionFor` in `lib/nav.ts`) | a tab strip of sibling routes under the header |
| List | `DataTableWithViews` + `DataTableColumnHeader` + faceted filters with counts + server pagination via `useListParams` + `selectColumn` + bulk actions | raw `<table>`, client-side paging of full lists |
| Create one thing (≤ 7 fields) | `DialogShell` size `md`, then navigate to its page to edit | a `/new` page |
| Create an entity | One-screen New X dialog (name plus one required field) → draft on its detail page; the guided wizard, template or import is the second button | a wizard as the only way in |
| Sign in / step-up | AuthProvider seam via `hooks/auth-queries`; `useStepUpGate` before money approvals (the API refuses them without a step-up) | importing an adapter directly |
| Create in steps | `DialogShell` + `Stepper` ("Step X of N", Back/Next, editable review step, fixed body height) | a wizard page |
| Revisitable settings | Form on the page (`SettingsSection`, sticky unsaved bar, versioned save) | a settings dialog |
| Inspect a row | `DetailSheet` with prev/next and `scrollKey` | navigating away for a peek |
| Delete | `DeleteDialog` with consequence text (`count` for bulk) | `confirm()` |
| Bulk change | `BulkConfirmDialog` / `BulkFieldDialog` + `toastBulk` (skipped items named by reason) + `useSticky` | silent partial success |
| Record page | `RecordLayout` / `AttributeCard` / `FieldRow`, or a settings form with a right rail | bespoke grids |
| Field | `FormField` (label, "(optional)", hint, inline error, `aria-invalid`) | placeholder-as-label |
| Upload a file | `FileUpload` (`components/shared/file-upload.tsx`): presigned upload through the Files API, progress, scan state, limits from Settings → Storage; pass the `fileId` on | `<input type="file">` with your own request, `FormData`, `fetch` PUT of a `File` (`check-standards` rule 13) |

`components/ui/*` are shadcn primitives adapted from the shared component library: do not edit them; wrap them in
`components/shared/`. Pages adapted from an earlier internal product keep their layout and copy but must be moved
onto the components above and the layer rules before they merge.

## States (every data surface)

- Loading: `PageSkeleton` / `RecordSkeleton` matching the real layout.
- Error: `QueryError` with Try again; record pages also offer a way back.
- Empty: `ListEmpty` / `EmptyState` with the create action; filtered-empty says so and offers Clear filters.
- Review them with `?mock=slow`, `?mock=error`, `?mock=empty` (`?mock=off` resets).

## Behaviour

- Production-affecting actions (publish, promote, move version, gate edits, deletes) confirm with the consequence stated.
- Workflows are the only deployable unit; agents are versioned settings pinned by a workflow at publish.
- Publishes are requested, validated (tests advisory, structural errors block) and approved by a different person in Reviews.
- Effects never return a value (`useEffect(() => { … })`): an expression body that returns a Promise or element crashes React.

## Copy

Product copy only: no developer explanations, no "(s)" plurals (use `plural()` from `src/lib/format.ts`), sentence case,
buttons say the action, placeholders start with "e.g." and never look like real records, numbers have units.

## Done means

1. `pnpm verify` passes.
2. Every changed route returns 200 and renders in Chrome without console errors.
3. An independent reviewer (a person or a fresh coding agent, in a browser, this file and `docs/console/page-plan.md` as the standard) has exercised the change, and its blockers and majors are fixed.
