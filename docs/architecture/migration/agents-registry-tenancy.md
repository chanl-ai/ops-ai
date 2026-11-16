# Agents registry, graph versions and channel tables: tenant isolation

Status: current, decided 2026-11-16. Part of the [agents lane](lane-agents.md), step 3. Paths are relative to
`services/agents-service/src/ops_agents/` unless written otherwise; each cited line was checked on 2026-11-16 and moves
with the tree.

## Classification

- Tenant-scoped and team-owned (team policy): `registry_agents`, `registry_guardrails`, `registry_skills`,
  `registry_widgets`, `registry_workflows`, `deployments`, `registry_publish_requests` (already has a tenant; gains
  `team_id` from its subject's team).
- Tenant-scoped through a parent (`team_owned_via`, tenant policy): the five `*_versions` tables and
  `registry_validations` (through `workflow_id`).
- `graph_versions`: tenant-scoped, owned through `registry_workflows` (`name` is the workflow id).
- Tenant policy only: `channel_messages`, `channel_cursors`, `thread_inbox`.
- `channel_files`: nothing reads or writes it and no tenant can be derived, so it is dropped (the down path recreates
  it empty).
- Nothing in the registry is install-wide. Seeds run only when a seed directory is set, inside the `local` tenant,
  owned by team `team_ops`.

## Where an existing row's tenant comes from

Agents database only, no service call. Precedence:

1. A direct reference: `template_copies(kind, record_id)`, `team_default_agents.agent_id`,
   `widget_deployments.agent_id`, `registry_publish_requests(kind, subject_id)`, `graph_threads.graph` naming
   `agent:<id>` or a workflow id.
2. A team-to-tenant map built from the distinct `(team_id, tenant_id)` pairs in agents tables that hold both
   (`graph_threads`, `graph_runs`, cases, mailboxes, `team_default_agents`, `template_copies`, `widget_deployments`,
   `eval_*`, `form_links`, memories, reviews).
3. `'local'`.

A team that maps to two tenants aborts the migration with the list. Version tables and validations take their parent's
tenant.

Seeded workflows shared across tenants are copied per tenant for exactly the (tenant, workflow id) pairs other tenants'
threads or publish requests point at: the `registry_workflows` row, its versions and its `graph_versions`, with name,
version and digest unchanged, so the digest check in `api/runs.py:94` still passes.

Preflight: an operator command lists teams in the agents database with no tenant mapping and teams that map to two
tenants. The migration refuses outside dev while gaps remain; dev falls back to `local`.

## Keys and lookups

- Agents: unique `slug` becomes `(tenant_id, slug)`; `_unique_slug` suffixes within the tenant (drop `any_team`).
- Guardrails and skills: `(team_id, slug)` stays; a `tenant_id`-leading index is added.
- The primary key stays `id` alone where ids are generated (`ag_`, `gr_`, `sk_`, `wf_` are random). The tenant goes
  into the key where ids are chosen or derived: `registry_widgets` PK `(tenant_id, id)` with a composite foreign key
  from its versions; `deployments` PK `(tenant_id, id)`; `channel_messages` `(tenant_id, deployment_id, message_key)`;
  `channel_cursors` `(tenant_id, deployment_id)`; `registry_workflows` `(tenant_id, id)`; `graph_versions` PK
  `(tenant_id, name, version)` and digest unique `(tenant_id, digest)`.
- Lookups before a tenant is known: widgets are safe (the mint key or session names the tenant and deployment); public
  forms use `form_links`, which has a tenant; channel deployments have no unauthenticated address;
  `/v1/workflows/refs` already requires a tenant.
- Install-wide paths that break under policies and change in the same commit as the stores:
  - The start-up serving reload reads `reg.rows()` as `local` only (`api/agent_registry.py:333-344`, called from
    `api/app.py:457`). It becomes one `system_tx(SERVE_PUBLISHED)` read of `(tenant_id, id, published_version,
    paused)`, then `go_live` for each, like `catch_up_assistants` (`api/ops_tools.py:147-152`).
  - `seed_workflows` and `seed_deployments` (`api/app.py:453`, `api/app.py:467`) move inside the seed and `local`
    block.
  - `rt.catalog` is keyed by agent id process-wide, so every route that resolves an agent from the catalogue reads its
    row through the store first.

## Channel backfill

- `thread_inbox` and `channel_messages`: by `thread_id` to `graph_threads`.
- `deployments`: the distinct `graph_threads.tenant_id` by `deployment_id`, then the team map when the team is not
  `''`, then `local`.
- `channel_messages` without a thread, and `channel_cursors`: the deployment's tenant.
- A deployment whose team is `''` takes the team of its threads when they all share one; otherwise it stays `''`
  (visible tenant-wide only).

## Order

One Alembic chain (`CHAIN="agents"`), taking the next free revision numbers.

- Migration A: add `tenant_id NOT NULL DEFAULT 'local'` and `registry_publish_requests.team_id`; backfill as above;
  swap keys; grant to the tenant role; drop `channel_files`. No policy yet, and the tables stay on `WAITING`. On SQL
  Server, inline unique keys are found by column as migration 0101 does.
- Commit B (one commit): the five registry stores and the other registry readers (`store/channel_list.py`,
  `store/actor_names.py`) become `Store` classes on `self.tx()` or `conn`, with `team_visible`, `owner_teams()`
  (`owner_team` deleted), and columns defaulting to the current tenant; the start-up and seed fixes above; markings;
  Migration C; `WAITING` removals; tests.
- Migration C: re-run the backfill idempotently for rows written as `local` between A and B, then `isolation_ddl` and
  `mssql_predicates_ddl` as 0104 does. C never ships ahead of B, because the old code writes as a role that bypasses
  the policy.
- Down: drop policies and grants; restore the install-wide keys, but refuse with a count when cross-tenant duplicates
  exist; delete per-tenant seed copies whose `(name, digest)` matches the `local` row.
- Both databases.

## Tests

One per failure mode, on both databases.

- Per table: tenant B's read, update and delete of A's row see zero rows; an insert naming A's tenant is refused.
- Agent slug and widget id collide across tenants: allowed; within a tenant: Conflict with the suffix. A guardrail or
  skill slug in two teams: allowed.
- After the upgrade, tenant B's thread pinned to a seed workflow resolves and its digest matches.
- A restart serves both tenants' published agents; tenant A's agent id from B's caller is NotFound.
- A widget mint key or session resolves its deployment's tenant; a thread start naming another tenant's
  `deployment_id` is NotFound. A `''` deployment: a team caller gets NotFound, the tenant-wide poller sees it.
- Backfill: a direct reference beats the team map; a team mapping to two tenants aborts; unmapped rows land in `local`;
  C run twice gives the same rows.
- `graph_list` and `_resolvable` show only the tenant's names.
- Down succeeds with no duplicates and refuses with the count otherwise.
- Markings: the tables are off `WAITING`; the isolation-sites list names the new reasons.
