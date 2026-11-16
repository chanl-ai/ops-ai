# Standards: tenant isolation and access

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `TN1` to `TN5` and `AC1`
to `AC5` are frozen. The design is in [identity and tenancy](../identity-and-tenancy.md) and
[roles and permissions](../roles-and-permissions.md); where this page and those disagree, they win.

Two guarantees an enterprise buyer asks about first: one tenant can never read another tenant's rows, and every
decision about who may do what is made in one place that can be audited.

## Tenant isolation

### TN1 Every tenant table is marked and policed

Rule: every table is marked `TENANT_SCOPED` (and `TEAM_OWNED` or `team_owned_via` where a team owns its rows) or
`system(reason)` in its metadata, and its migration installs the row-level security policy for that marking on
PostgreSQL and the security predicate on SQL Server.
Why: an unmarked table has no isolation policy on either database, and the query filter alone is one forgotten `WHERE`
from showing one bank's rows to another.

Today (`deploy/database/tests/test_isolation_markings.py:20`): the `WAITING` list names about 40 tables with no policy
yet (tools, agents, models and platform services).

Pattern (`services/agents-service/migrations/versions/0103_eval_cases_runs.py:19`): a new table imports the markers
and the policy DDL from `ops_store.schema`.

```python
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl
```

Check: `deploy/database/tests/test_isolation_markings.py` (every table marked; the waiting list only shrinks). It runs
on a full CI plan and nightly. Needed: run it in the `checks` job on every pull request.

### TN2 Every read and write runs inside an isolated transaction

Rule: every statement against a tenant-scoped table runs inside `ops_store.isolation.isolated_tx` (each service wraps
it as `tenant_tx`), `tenant_wide(reason)` or `system_tx(reason)`; a store never calls `engine.begin()` or
`engine.connect()` itself.
Why: `isolated_tx` sets the database role and the tenant and team context the policies read
(`packages/ops_store/src/ops_store/isolation.py:209`); a raw connection runs as the owner, which on the compose
superuser bypasses row-level security, and relies on a hand-written filter.

Today (`services/tools-service/src/ops_tools/store/send_policies.py:61`): a raw connection with a hand-written filter.

```python
q = sa.select(t).where(t.c.tenant_id == tenant_id, t.c.team_id == team_id)...
async with self.engine.connect() as c:
```

The audit counted 183 raw `engine.begin()` or `engine.connect()` sites in service code (104 in agents-service, 63 in
tools-service).

Pattern (`services/agents-service/src/ops_agents/store/cases.py:160`, through
`services/agents-service/src/ops_agents/store/tenancy.py:75`):

```python
async with tenant_tx(self.engine) as c:
    ...
def tenant_tx(engine: AsyncEngine) -> AbstractAsyncContextManager[AsyncConnection]:
    return isolation.isolated_tx(engine, role=TENANT_ROLE)
```

Check: `packages/ops_store/tests/test_isolation_sites.py` lists every widening by reason, and `NoTenantError`
(`isolation.py:55`) refuses a transaction with no context. Nothing fails on a raw `engine.begin()`. Needed: extend
`test_isolation_sites.py` to fail on `engine.begin` or `engine.connect` in `store/` outside a shrink-only list of
system paths, and run it in the `checks` job.

### TN3 Team scope comes from one helper

Rule: every query of a team-owned table carries `team_visible(table)`; no store writes its own team `WHERE`, and no
code filters another team's rows out of a result in Python.
Why: one filter, tested once, replaces a filter per query that each new query can forget; a filter applied after the
read grows with every team and cannot be enforced by the database.

Today (`services/agents-service/src/ops_agents/api/publish_reviews.py:150`): the tenant's requests are read, then
other teams' rows are dropped in Python.

```python
owners = await _owners(rt, requests, versions)
requests = [r for r, owner in zip(requests, owners, strict=True) if owner is None or owner == acting]
```

Pattern (`services/agents-service/src/ops_agents/store/cases.py:201`):

```python
where: list[Any] = [cases.c.team_id.in_(teams), team_visible(cases)]
```

Check: `packages/ops_store/tests/test_team_reads.py` and `test_team_visible.py`; `scripts/team_isolation_probe.py`
against a running stack.

### TN4 Tenant from the token, team from the header, 404 for the rest

Rule: the tenant comes only from the verified token and the team from `X-Team-Id` checked against it; a body, path or
query never names either, and a record of another team answers 404.
Why: a caller cannot name their way into another tenant (insecure direct object reference, OWASP ASVS V4.2), and a 404
tells them nothing about what exists.

Today: no known breach in the services; `packages/ops_store/tests/test_isolation_sites.py` fails on a service that
sets its own tenant or team.

Pattern (`packages/ops_identity/src/ops_identity/fastapi.py:214` and
`services/agents-service/src/ops_agents/store/cases.py:176`): the caller is a dependency, and a read of one record
carries the team filter so a foreign id finds nothing.

```python
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
q = sa.select(cases).where(cases.c.id == case_id, cases.c.team_id.in_(teams), team_visible(cases))
```

Check: `scripts/team_isolation_probe.py`; `packages/ops_store/tests/test_team_reads.py`.

### TN5 A wider read names its reason

Rule: `tenant_wide` and `system_tx` take a reason that is a named constant, and every call site is listed by reason
in `packages/ops_store/tests/test_isolation_sites.py`.
Why: a reviewer can read the whole list of places that see more than one team and judge each one.

Today: no breach; the list is complete.

Pattern (`services/platform-service/src/ops_platform/store/signin.py:668`):

```python
async with self.db.system_tx(SIGNIN_LOOKUP) as c:
```

Check: `packages/ops_store/tests/test_isolation_sites.py` (a new or unlisted call site fails naming the file).

## Access

### AC1 Every decision goes through `can()`

Rule: who may do what is decided only by `ops_access.can()` over the roles grid and team policies; code never compares
a role name, checks an owner, an id prefix or an `is_admin` flag.
Why: one decision point is what an access review can audit (SOC 2 CC6.1); a role name in code is a permission nobody
can change without a release.

Today (`apps/console/src/lib/auth/providers/platform.ts:70` and
`apps/console/src/components/access/members-panel.tsx:42`, rows E22 and E20 of `access-exceptions-allowlist.txt`): the
console compares role names. E22 is decided (the session role is retired) and its lines go in the console's lane.

```ts
const workspaceRole = (r) => (r === 'admin' ? 'admin' : r === 'viewer' ? 'viewer' : 'member');
```

Pattern (`services/agents-service/src/ops_agents/api/routers/activity.py:252` and
`apps/console/src/components/channels/hub/pages.tsx:116`):

```python
can(caller_of(me), "activity", "view", team=current_team() or me.team_id, what="the activity list")
```

```ts
const mayConnect = useCan(connect?.area ?? 'deployments', connect?.action ?? 'create') === true;
```

Check: `scripts/check_access_exceptions.py` (role-name compares, refusals, locks and policy defaults outside `can()`;
an `is_admin` flag or a role tested against a list of names is never allowed; owner compares and role-name compares
are counted per lane in `scripts/access-baselines/`, which may only fall; a register row with no decision exits 1;
`--self-test` plants one of each shape; `--commits` lists the exception lines a pull request adds, which need an approving
review on it from a maintainer listed in `.github/standards-maintainers.txt`, checked by CI's `maintainer-review` job). It is on the `make checks` list, so it runs in
pre-commit, in the pull-request `checks` job and in `make verify`.

### AC2 An exception is written down before it exists

Rule: a refusal outside `can()` exists only when the exceptions register in
[roles and permissions](../roles-and-permissions.md) records it with a decision, and `access-exceptions-allowlist.txt`
names its row.
Why: a reviewer finds every exception, with the decision behind it, in one list; the list may only shrink.

Today: 185 lines in the allowlist (about 314 findings registered).

Pattern (`access-exceptions-allowlist.txt:6`): one line per site, naming the shape, the count and the register row.

Check: `scripts/check_access_exceptions.py` (a new, stale or unregistered exception fails).

### AC3 The roles page changes with the code

Rule: a new permission cell, team policy or approval is written in [roles and permissions](../roles-and-permissions.md)
in the same change, with its default and who changes it.
Why: the grid on the page is the grid in the code; a cell added in code alone is invisible to the people who set it.

Today: no breach.

Check: `uv run python scripts/roles_matrix.py --check` in the CI `checks` job.

### AC4 Policy values are read, never assumed

Rule: a team policy's value comes from `ops_access.policies.policy(principal, key)`; code never writes the default
inline.
Why: a default written inline is a second source of truth for the policy, and the two disagree the first time a team
changes it.

Today: 21 policy-default sites registered in the allowlist; 3 reads outside `policy()` (2 in tools-service, 1 in
platform-service) counted in their lanes' baseline files.

Pattern (`packages/ops_access/src/ops_access/policies.py:362`): `policy(p, key)` with `check_value` on write.

Check: `scripts/check_access_exceptions.py` (policy-default shape; the policy-read shape for a value read some other
way).

### AC5 Service calls carry the least scope

Rule: a service token names the scopes the call needs (`scopes=["agents:view"]`), and a service refuses a call whose
token lacks the scope.
Why: a leaked or misused service token can then do one thing, and the scope names it in the log.

Today: no known breach.

Pattern (`services/kb-service/src/ops_kb/app.py:154`):

```python
ServiceClient.for_settings(settings, http, service="kb", audience="agents", scopes=["agents:view"], timeout=5)
```

Check: `packages/ops_identity/tests/` (scope checks on `current_service`). Needed: a test over every internal route
asserting the scope it requires is declared.
