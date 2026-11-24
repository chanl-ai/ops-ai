# Standards: console, SDKs and CLI

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `UI1` to `UI7` are frozen.
The console's own rules are in `apps/console/CLAUDE.md`; the SDK's in `sdk/CLAUDE.md`.

A screen shows what one API call returned. It never joins, filters, counts or sums over fetched lists, it reads through
hooks, and new screens call the generated SDK. The SDKs are generated from the services' documents and never edited by
hand; the CLI calls the SDK.

## UI1 No joins, counts or sums in the browser

Rule: a screen gets every join, total, count, label and filtered list it shows from one API call; the browser never
joins two lists by id, filters a fetched list, counts over it or `.reduce()`s it.
Why: a total computed over one page is wrong once the list pages; a join over a 100-row list loses every row past 100;
each extra list costs a request. The audit found 59 places and about 600 statements per screen because of them.

Today (`apps/console/src/components/channels/hub/pages.tsx:122`): a week's activity summed over the current page.

```ts
const week = counted.length ? counted.reduce((n, c) => n + (c.activity7d ?? 0), 0) : null;
```

Also `apps/console/src/components/shared/team-name.tsx:11` (a per-row join of `teamId` to the person's teams) and
`apps/console/src/app/chat/_parts/chat-workspace.tsx:60` (a 100-row knowledge-base list joined to the agent's ids).

Pattern (`apps/console/src/hooks/systems-queries.ts`): the hook asks the API for the shape the screen shows; the row
carries its labels and the list carries its facets.
A list the person searches is searched on the server: a table through the data table's server mode, a picker through
`EntityPicker` or `SearchSelect` over an `/options` source, any other list (a gallery, a document's pieces) through
`useServerList` (`apps/console/src/hooks/server-list.ts`). Rule 16's `listFilter` fails a list searched in the browser.

Check: `apps/console/scripts/check-standards.mjs` rule 23 fails on `.reduce(` and `.filter(...).length` inside
components and pages, on `pageSize` above 50 outside the options hooks, and on `fetch(` outside `lib/api`, with
today's sites held per file in `apps/console/scripts/data-baseline.json`, which may only fall. Needed: the same for
`.find(` over a list hook's data.

## UI2 One direction: pages, hooks, contract, client

Rule: pages read through hooks; hooks call the `OpsApi` contract; the contract's HTTP implementation or `sdk()` sends;
components take props only and never import `@/lib/api` values.
Why: each layer swaps without touching the others, and the mock serves every screen the same way the services do.

Today: no breach beyond the two raw fetches in `LY6`.

Pattern (`apps/console/CLAUDE.md`, "Layers"): type → contract → `http.ts` → mock → hook → page.

Check: `apps/console/scripts/check-standards.mjs` rules 2, 3 and 17 (`apps/console/scripts/check-standards.mjs:63`).

## UI3 Sample data lives in the mock

Rule: fixtures and sample data live only in `apps/console/src/lib/api/mock/` and test fixtures; a screen on real
services never shows sample data, never falls back to the mock on an error, and product copy never names the sample
tenant.
Why: sample data on a real screen reads as real data.

Today (`apps/console/src/components/auth/login-form.tsx:73`): the sample bank's name as product copy.

```tsx
<AuthHeading title="Welcome back" description="Sign in to Harbor & Pine Ops AI" />
```

The audit counted eight such places, and `lib/api/index.ts:44` serves the mock for any area whose service URL is unset.

Pattern (`apps/console/src/lib/api/mock/`): the one place fixtures live.

Check: `apps/console/scripts/check-standards.mjs` rules 1 and 20. Needed: a ratchet on the sample tenant's name outside
`mock/` and `seed/`, at zero once branding comes from settings.

## UI4 Lists page on the server through the shared parameters

Rule: every list screen uses `useListParams` and the data table, sends page, size, search and filters to the API, and
shows the API's `pagination` and `facets`.
Why: one table component handles paging, sorting and selection; a list that fakes pagination breaks at the first large
team (`DA5`).

Today (`apps/console/src/lib/api/platform-http.ts:78`): pagination invented from the array length.

```ts
return { data, pagination: { page: 1, pageSize: Math.max(data.length, 1), total: data.length, totalPages: 1, ... }, facets: {} };
```

Pattern (`apps/console/src/components/channels/hub/pages.tsx:112`):

```ts
const list = useListParams<Record<string, never>>('name');
const q = useChannels({ page: list.params.page, pageSize: list.params.pageSize, search: list.params.search, type: [type] });
```

Check: `apps/console/scripts/check-standards.mjs` rules 6 and 22.

## UI5 Every data surface has its three states

Rule: every screen that loads data shows a loading state, an empty state and an error state; the error shows the API's
message and request id.
Why: a person must know whether there is nothing or something failed, and support needs the id.

Today: covered by the walk; no screen is known to lack a state.

Check: `scripts/agents/ui_walk.mjs` with `STATES=1` (`?mock=slow`, `?mock=error`, `?mock=empty` on the mock).

## UI6 The SDKs are generated, and both languages move together

Rule: the SDKs' generated layer is never edited by hand; the hand-written nouns match one for one in Python and
TypeScript; a route is missing from the SDK because the service's `x-ops-public` marker is, never because the generated
file is.
Why: the documents are the source; a hand edit is overwritten by the next `make openapi`.

Today: no breach; the drift check runs only on a full plan and nightly (`MD2`).

Pattern (`sdk/generate.py:1`): the generator, with `--check` as the drift test.

Check: `make sdk-verify` (`uv run python sdk/generate.py --check` and both SDKs' tests).

## UI7 The CLI calls the client

Rule: the CLI (`sdk/python/src/ops_ai/_cli/`) calls SDK client methods only; it never builds an HTTP request or reads a
route path.
Why: the same reason as `LY6`; the CLI is a thin peer of the console.

Today: no breach.

Pattern (`sdk/python/src/ops_ai/_cli/agents.py:9`):

```python
from .common import client, emit, parser, refuse
```

Check: no check yet. Needed: an import rule that `_cli/` imports no `httpx` and no `_transport`.
