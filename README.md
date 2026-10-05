# Ops AI

Status: current.

Ops AI is a design for an operational AI platform for banks, plus a working console that shows it.
The console (`apps/console/`) is a Next.js app running against an in-memory mock API: it shows what
agents did, what is waiting on a person, and the configuration behind both, for a fictional bank,
Northfield Bank. **Agent Studio** covers agents, workflows and the human review queue; **Data Hub**
covers knowledge sources and tools. The specs in `docs/` describe the backend that would replace the
mock. No backend code exists yet. It is for engineers, architects and risk reviewers evaluating or
building such a platform.

## Run it

From a clean clone. Needs Node 20 or later and pnpm 10 (`corepack enable` provides it).

```bash
pnpm install
pnpm dev          # http://localhost:3016
```

No credentials, services or environment variables are needed: with no backend configured the
console uses the in-memory mock, and its state resets on reload. To see loading, error and empty
states, add `?mock=slow`, `?mock=error` or `?mock=empty` to any URL; `?mock=off` resets.

To point the console at a real API, set `NEXT_PUBLIC_OPS_API_URL`. Responses use the
`{ success, data }` envelope; routes are in `apps/console/src/lib/api/http.ts`.

## Three common tasks

### Add a page

1. Add the route under `apps/console/src/app/<route>/page.tsx`.
2. Read data only through hooks in `apps/console/src/hooks/`; build the page from the components listed in `apps/console/CLAUDE.md` (`PageLayout`, `DataTableWithViews`, `DialogShell`, `DetailSheet`, `RecordLayout`).
3. Handle loading, error and empty states, and check each with `?mock=slow|error|empty`.
4. Add the page to `docs/ui/page-plan.md`.

### Add an API operation end to end

| Step | File |
|---|---|
| 1 Type | `apps/console/src/lib/types/<area>.ts` |
| 2 Contract method | `apps/console/src/lib/api/<area>-contract.ts` (or `contract.ts`) |
| 3 HTTP client | `apps/console/src/lib/api/<area>-http.ts` (or `http.ts`) |
| 4 Mock | `apps/console/src/lib/api/mock/`, the only place fixtures exist |
| 5 Hook | `apps/console/src/hooks/<area>-queries.ts` |

The backend version of the same operation is described in `docs/backend/overview.md` (contract flow).

### Run verify

```bash
pnpm verify
```

This type-checks the console and runs `apps/console/scripts/check-standards.mjs`. `pnpm install`
installs a pre-commit hook (`.githooks/pre-commit`) that runs the same command.

## Repo map

| Path | What it holds |
|---|---|
| `apps/console/` | The Ops AI console (Next.js, mock API). Working rules in `apps/console/CLAUDE.md` |
| `docs/` | Problem statement, architecture and decision records, topic specs, plan, UI plan. Index: `docs/README.md` |
| `services/` | One folder per planned backend service, each with a README. No code yet |
| `packages/contracts/` | Planned home of the OpenAPI and JSON Schema contracts generated from the console's typed contract |
| `deploy/compose/` | Planned local development stack |
| `CONTRIBUTING.md` | Doc standards, code standards, verify, commit convention |
| `AGENTS.md` | Rules for coding agents working in this repo |

## Not built

Persistence (mock state resets on reload), authentication, the backend services, and saved custom views.

## Licence

Apache-2.0. See `LICENSE`.
