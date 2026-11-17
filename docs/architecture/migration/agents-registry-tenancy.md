# Agents registry, graph versions and channel tables: tenant isolation

Status: current, decided 2026-11-16. Part of the [agents lane](lane-agents.md), step 3. Paths are relative to
`services/agents-service/src/ops_agents/` unless written otherwise; each cited line was checked on 2026-11-16 and moves
with the tree.

## Classification

- Tenant-scoped and team-owned (team policy): `registry_agents`, `registry_guardrails`, `registry_skills`,
  `registry_widgets`, `registry_workflows`, `deployments`.
- `registry_publish_requests`: tenant policy only. It gains `team_id` from its subject's team, but reviewers outside
  the owning team (the security team, for one) must still read a request, so the team is checked in code through
  `can()`, not by the row policy.
- Tenant-scoped through a parent (`team_owned_via`, tenant policy): the five `*_versions` tables and
  `registry_validations` (through `workflow_id`).
- `graph_versions`: tenant-scoped, owned through `registry_workflows` (`name` is the workflow id).
- Tenant policy only: `channel_messages`, `channel_cursors`, `thread_inbox`.
- `channel_files`: nothing reads or writes it and no tenant can be derived, so it is dropped (the down path recreates
  it empty).
- Nothing in the registry is install-wide. Seeds run only when a seed directory is set, inside the `local` tenant,
  owned by team `team_ops`.

## Where an existing row's tenant comes from

Agents database only, no service call. A seed's record (team `team_ops`, with a version saved or published by
`seed`) stays in `local`, ahead of every rule below, because the start-up seed looks for it there by its fixed id; it
is never counted as a gap. Another tenant's thread on a seeded agent does not resolve it once the policies hold; a
seeded workflow is copied into each tenant that runs it (Migration C). Otherwise, in order:

1. A direct reference: `template_copies(kind, record_id)`, `team_default_agents.agent_id`,
   `widget_deployments.agent_id`, `registry_publish_requests(kind, subject_id)`, `graph_threads.graph` naming
   `agent:<id>` or a workflow id.
2. A team-to-tenant map built from the distinct `(team_id, tenant_id)` pairs in agents tables that hold both
   (`graph_threads`, `graph_runs`, cases, mailboxes, `team_default_agents`, `template_copies`, `widget_deployments`,
   `eval_*`, `form_links`, memories, reviews), plus the `team=tenant` pairs an operator names in
   `OPS_REGISTRY_TEAM_TENANTS` for a team nothing else places (`deployment:<id>=tenant` places a deployment).
3. `'local'`.

Version tables and validations take their parent's tenant. The statements are in
`services/agents-service/src/ops_agents/store/registry_tenants.py`, shared by the migration and the preflight.

When a reference or a team names more than one tenant:

| Case | Outside dev | Dev |
|---|---|---|
| A team seen in no tenant | The migration stops with the list | The rows take `local` |
| A deployment with no team that no thread names | The migration stops with the list | `local` |
| `local` and exactly one other tenant | The other tenant: outside dev `local` holds only rows nothing could place | `local` |
| A record referenced only from `local` | Its team's tenant by the rows above (a team in one real tenant gives that tenant) | `local` |
| Two or more tenants other than `local`, for a team or for a record's references (any kind) | The migration stops with the list | `local` |

Offline SQL cannot check first: a team or record with two tenants writes NULL into the NOT NULL column, so the
statement fails; an unmapped team's rows take `local`.

Seeded workflows shared across tenants are copied, in Migration C, per tenant for exactly the (tenant, workflow id) pairs other tenants'
threads or publish requests point at: the `registry_workflows` row (without its draft), its versions and its
`graph_versions`, with name, version and digest unchanged, so the digest check in `api/runs.py:94` still passes. Each
copy's source is chosen before any copy is made (`local` when it holds the workflow, else the first holder by name),
and each copied workflow version carries `review_id` `copied`.

Preflight: `make -C services/agents-service registry-tenant-preflight` lists, by the outside-dev rules, each team with
no tenant, each deployment with no team and no thread, each team and each record with two or more tenants other than `local`, and exits 1 when any exists. It only
reads, through a `system_tx` past the tenant as the connecting login (row security off, which PostgreSQL refuses for a
login that does not bypass it). It never drops or alters a policy. On SQL Server no login can read every tenant without
changing a policy, so the preflight exits 2 and says to run the upgrade, which makes the same check before it changes a
row.

## Keys and lookups

- Agents: unique `slug` becomes `(tenant_id, slug)`; `_unique_slug` suffixes within the tenant (drop `any_team`).
- Guardrails and skills: `(team_id, slug)` stays; a `tenant_id`-leading index is added.
- The primary key stays `id` alone where ids are generated (`ag_`, `gr_`, `sk_`, `wf_` are random). The tenant goes
  into the key where ids are chosen or derived: `registry_widgets` PK `(tenant_id, id)` with a composite foreign key
  from its versions; `deployments` PK `(tenant_id, id)`; `channel_messages` `(tenant_id, deployment_id, message_key)`;
  `channel_cursors` `(tenant_id, deployment_id)`; `registry_workflows` `(tenant_id, id)`; `graph_versions` PK
  `(tenant_id, name, version)` and digest unique `(tenant_id, digest)`.
- Agents keep the key `id`. Every id derived from fixed inputs includes the tenant, so two tenants never derive one id
  and one tenant's `go_live` cannot replace another's catalogue entry: a team's Ops Assistant is made as `ag_ops_` and
  24 hex of a SHA-256 of tenant and team (`api/ops_tools.py` `ops_assistant_id`). An assistant made earlier keeps its
  `ag_ops_<team>` id: `assistant_id` looks the team's assistant up in the caller's tenant by either id with that team
  as owner first and derives the new id only to create one; the start-up catch-up accepts either. Seeded agents keep
  their seed-file ids, because seeds load only into `local` and no other path creates an agent with a chosen id
  (creates take random `ag_` ids). A seed agent whose id or slug a row outside `local` already holds is skipped with
  a `seed_agent_held_elsewhere` warning, and the service starts without it. The catalogue stays keyed by id; the two-tenant test is in
  `tests/api/test_registry_tenant_catalogue.py`.
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

One Alembic chain (`CHAIN="agents"`).

- Migration A, `0106_registry_tenant_columns`:
  - `tenant_id NOT NULL DEFAULT 'local'` on the five registry tables, their version tables, `registry_validations`,
    `graph_versions`, `deployments`, `channel_messages`, `channel_cursors` and `thread_inbox`;
    `registry_publish_requests.team_id` from its subject's team.
  - The backfill above, with the checks; a deployment with no team takes its threads' team when they share one.
  - Keys: agents `(tenant_id, slug)`; `graph_versions` primary key `(tenant_id, name, version)` and digest unique
    `(tenant_id, digest)`; `(tenant_id, team_id)` indexes on guardrails, skills and publish requests.
  - Grants to the tenant role on PostgreSQL; `channel_files` dropped.
  - No row policy, and the markings are unchanged, so the tables stay on `WAITING`. The model columns default to
    `local` on the server, so the stores of today keep working unchanged.
- Commit B (one commit): the five registry stores and the other registry readers (`store/channel_list.py`,
  `store/actor_names.py`) become `Store` classes on `self.tx()` or `conn`, with `team_visible`, `attempt()` at caught
  sites, and columns defaulting to the current tenant; the start-up and seed fixes above; markings;
  Migration C; `WAITING` removals; tests. These key changes wait for B, because today's stores name the current keys:
  - `registry_workflows` `(tenant_id, id)`, with the seed copies that need it (`store/graphs.py:208` would return each
    copied version twice) and a composite foreign key from its versions;
  - `registry_widgets` `(tenant_id, id)` and the composite foreign key from its versions (today's stores write a new
    version as `local` under a parent in another tenant);
  - `deployments` `(tenant_id, id)`, `channel_messages` `(tenant_id, deployment_id, message_key)`, `channel_cursors`
    `(tenant_id, deployment_id)`: `store/channels.py:127`, `:173` and `:198` upsert on the current keys.
- Migration C: re-run the backfill idempotently for rows written as `local` between A and B; the seed copies; the key
  changes above; then `isolation_ddl` and `mssql_predicates_ddl` as 0104 does. C never ships ahead of B, because the old
  code writes as a role that bypasses the policy.
- Every backfill in A and C runs in committed batches (as 0104 does), so no lock lasts the whole fill. C drops the
  `local` server default A gave each `tenant_id` column, once the stores write the caller's tenant, so a write that
  names no tenant is refused instead of landing in `local`. Each down path drops the column with
  `mssql_drop_default=True`, since SQL Server refuses to drop a column that still has a default.
- Each registry store's `owner_team()` is one call to the shared `Store.owner_teams` with the reason `OWNER`, on the
  connection it is given.
- Down: A refuses with a count while two tenants hold one agent slug, graph version or digest, and otherwise restores
  the install-wide keys, recreates `channel_files` empty and drops the columns. C's down drops policies and grants; 0108's
  down deletes each workflow copy whose versions all still carry `copied` (one a tenant has published to since is
  kept, and the down refuses with the count), then each `graph_versions` row another tenant holds with the same name,
  version and digest, keeping the workflow's holder.
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
