# Phase 3, console lane

Status: current, 2026-11-15. The console's data layer moves onto the list contract and the fields the service lanes
return: hooks and `lib/api` change, pages and components stay. It starts the day C2 lands, against the mock and the
pilot's services, and closes two to three days after the agents lane merges and its SDK is regenerated.

## Inputs

| Input | Where |
|---|---|
| The list contract and the three console rules | [components.md](components.md), C2: `apps/console/src/lib/api/contract.ts`, `apps/console/src/hooks/options-queries.ts`, `apps/console/scripts/check-standards.mjs` |
| The fields each lane returns | The `Out` models in each lane page; the regenerated SDK under `sdk/typescript` after each merge |
| The console today | `apps/console/src/lib/api/` 108 files (49 `*-http.ts`, 43 `*-contract.ts`, `platform-http.ts`, `http.ts`, `index.ts`, `mock/` 44 files); `apps/console/src/hooks/` 60 files; `apps/console/src/lib/auth/` |
| Its use cases | 91: `make usecase-coverage SERVICE=console` lists them |
| The sites, counted on `develop` | 13 fetches of 100 or 200 rows; 12 joins by id; 13 counts and 8 `.reduce(` in components; 3 `fetch(` outside `lib/api`; `platform-http.ts` inventing pagination; `team-name.tsx` labelling from a second list; 5 role-name compares (`lib/auth/providers/platform.ts`, `hooks/me-queries.ts`, `components/access/members-panel.tsx`); `process.env` read in four files (`lib/api/index.ts`, `proxy.ts`, `components/shared/ui-feedback.tsx`, `lib/utils/logger.ts`) |

## Size

4 to 6 builder days, against 3 to 4 in the site-by-site plan. Basis: the 49 `*-http.ts` clients onto the contract's
`ListParams` and `ListResult` with `facets` (1.5); the 59 places where a hook or screen joins, counts or refetches,
each onto the field the lane now returns (2 to 2.5); the 5 role compares onto `useCan` and the session role deleted
(0.5); the environment read in two files (0.1); the mock serving the same shapes (0.5); walks at 1440 and 390 wide
(0.5). One builder.

## What is replaced and what is kept

| Replaced | Kept |
|---|---|
| `lib/api/platform-http.ts`'s pagination; every `*-http.ts` list call onto `ListParams` with `ids=` and `search=`; `contract.ts` already carries `facets` | Every `*-contract.ts` type that the regenerated SDK confirms |
| Hooks that fetched 100 or 200 rows to label or count: they read the label and count fields the lane returns; the 12 joins, 13 counts and 8 `.reduce(` deleted; the 3 `fetch(` outside `lib/api` moved into it | Pages under `src/app` and components under `src/components`; `components/shared/` and the data table |
| `lib/auth/providers/platform.ts`'s session role of admin, member or viewer deleted; each screen asks `useCan` for its cell (`lib/nav.ts` already does); `hooks/me-queries.ts` reads `/v1/me` once; `members-panel.tsx` keeps its badge with a reason | `lib/nav.ts`, `useCan` |
| `process.env` read only in `lib/api/index.ts` and `proxy.ts`; `ui-feedback.tsx` and `logger.ts` take their values from there | |
| `lib/api/mock/` answers the same shapes as the services: `facets`, labels and counts in the list, one `/v1/me` | Sample data stays in the mock only |

## Target shapes

```ts
// apps/console/src/lib/api/contract.ts (C2 landed this)
export type ListParams = { page?: number; pageSize?: number; search?: string; sortBy?: string;
  sortOrder?: 'asc' | 'desc'; ids?: string[]; filters?: Record<string, string[]> };
export type ListResult<T> = { data: T[]; pagination: Pagination; facets?: Record<string, FacetValue[]> };

// apps/console/src/hooks/agent-queries.ts, after
export function useAgentPage(agentId: string) {
  return useQuery({ queryKey: ['agent-page', agentId], queryFn: () => api.agents.page(agentId) });
  // one call: the agent, its tools with names and approval, its knowledge bases with names and colours, its guardrails
}

// apps/console/src/hooks/options-queries.ts, after
export function useKnowledgeBaseOptions(ids: string[] | undefined, search: string) {
  return useQuery({ queryKey: ['kb-options', ids, search], queryFn: () => api.knowledge.list({ ids, search, pageSize: 50 }) });
}

// a screen, after
const { data } = useRunsList(params);             // data.facets.workflowId carries names; nothing joined here
const may = useCan('agents.publish');             // never a role name
```

## Step order

1. Day one, against the mock: `platform-http.ts` and the `*-http.ts` list calls onto the contract; the mock serves
   `facets`, labels and counts; the three console rules green on the mock.
2. As each lane merges and its SDK regenerates, in merge order: the hooks for that service's screens read the fields
   it now returns; the joins, counts and refetches for those screens deleted; the screen walked at 1440 and 390 wide.
3. Access: the 5 role compares onto `useCan`; the session role deleted; `/v1/me` read once.
4. Environment reads into the two files.
5. After the agents lane: the agent page and the runs screens onto `useAgentPage` and the faceted runs list; the
   last `pageSize: 200` gone.
6. Use cases and `pnpm verify` green; pull request; staging deployed and walked.

## Commands

| Step | Command |
|---|---|
| Type-check, the standards check and the console tests | `make console-verify` (`pnpm --filter @ops-ai/console verify`) |
| The 91 console use cases, in parallel | `make usecase-batch UCS="<the ids from make usecase-coverage SERVICE=console>"` |
| Use cases the change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` |
| Walk the changed screens headless at 1440 and 390 wide, as an admin and a member | `make agent-ui-walk` |
| The gate | `make verify` |
| After the merge | `make stg-deploy REF=<merge commit>`; `make stg-health` |

## Acceptance

| Check | Green when |
|---|---|
| The three console rules | Zero `pageSize` above 50 outside `options-queries.ts`; zero `.reduce(` or `.filter(...).length` in components and app; zero `fetch(` outside `lib/api` |
| Joins and counts | The 12 joins and 13 counts gone; every label and count on a screen comes from the list that shows it |
| Access | Zero role-name compares outside the badge; the session role gone; the per-lane role-name baseline for the console at zero |
| Environment | `process.env` in `lib/api/index.ts` and `proxy.ts` only |
| Mock | The mock serves the same shapes; the console runs against it with every state (loading, empty, error) |
| Behaviour and staging | `make console-verify`, the 91 use cases and `make verify` green on the merge commit; staging deployed with the console walk green; every changed screen walked at both widths as an admin and a member |

## Branch and pull request

Branch `refactor/console-screen-shaped-reads` from `origin/develop`, one pull request into `develop`, rebased after
each lane merge it depends on. Commit subject at most 72 characters, body at most three lines. A reviewer who did not
write it approves against this page and `apps/console/CLAUDE.md`. Merge order: last.

## What not to touch

- Pages under `apps/console/src/app` and components under `apps/console/src/components`, apart from deleting a join,
  count or role compare inside one and reading the field that replaces it.
- `apps/console/src/components/ui/`; wrap in `components/shared/` if something is missing.
- The services; a field a screen needs that no lane returns is a gap written on that lane's page, not a join here.
- `sdk/`; the console reads the regenerated SDK and never edits it.
