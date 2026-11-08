# Embed app: working rules

Status: current.

This app serves what a bank's own web pages load: the chat widget for a published deployment and the hosted forms a
workflow sends to a person. It is a Next.js 16 app; read the version notes in @AGENTS.md before writing Next.js code.
Rules shared with every folder: [Working in one folder](../../CLAUDE.md#working-in-one-folder).

## What it owns

| Path | Holds |
|---|---|
| `src/app/embed/[deployment]/page.tsx`, `src/embed-chat.tsx`, `src/frame.tsx` | The framed chat for one deployment |
| `src/app/f/[slug]/page.tsx`, `src/hosted-form-page.tsx` | A hosted form, opened from the link a workflow sends |
| `src/widget-api/index.ts` | What `@/lib/api` resolves to here: only `api.chat`, over the widget API (`/v1/widget/{deployment}`) with the session the loader passed in; any other area rejects |
| `src/config.ts` | The deployment's public config, read on the server from agents-service `GET /v1/widget/{id}/config` with the framing page's origin |
| `src/proxy.ts`, `next.config.ts` | `frame-ancestors` for `/embed/` from each deployment's origins; no referrer and no framing for `/f/`; `/embed/v1.js` and the widget API rewritten to agents-service |
| `scripts/check-bundle.mjs` | Builds the app and fails when the bundle holds the console's API client or its mock |

The chat components themselves are the console's (`apps/console/src/components/`), drawn through the
`@/lib/api` alias in `next.config.ts`. A change to them is a console change: `pnpm verify` in `apps/console`
type-checks this app as well.

## Run and check from this folder

| Task | Command (in `apps/embed/`) |
|---|---|
| On the live stack | `make up` from the root runs it on :3020 (`OPS_EMBED_PORT`) against agents-service; `make health` probes `/embed/v1.js` |
| Alone | `pnpm dev` (:3019); set `OPS_EMBED_AGENTS_URL` to an agents-service, since the default `http://127.0.0.1:8600` is no port the stack uses |
| Type-check | `pnpm typecheck` |
| Bundle holds no console client | `pnpm check:bundle` (builds into `.next-bundle-check`, then scans it) |

## Rules

| Rule | Detail |
|---|---|
| No console routes | Code here reaches agents-service only through the widget API. A console hook that calls another area fails loudly, by design of `src/widget-api/index.ts` |
| Origins are configuration | A deployment's allowed origins come from its config; agents-service refuses a widget call from an origin it does not list, and the app never widens that |
| Tokens stay out of referrers | A hosted form's address carries its token, so `/f/` pages keep `Referrer-Policy: no-referrer` and `frame-ancestors 'none'` |

## Reference docs

| Topic | Doc |
|---|---|
| Putting the chat on a bank page | [docs/console/embedding-the-chat.md](../../docs/console/embedding-the-chat.md) |
| Hosted forms in workflows | [docs/guide/workflows.md](../../docs/guide/workflows.md) |
| The widget routes | `services/agents-service/src/ops_agents/api/routers/widget.py`; they are mounted with `include_in_schema=False` (`services/agents-service/src/ops_agents/api/app.py:495`), so `openapi.json` does not list them |
