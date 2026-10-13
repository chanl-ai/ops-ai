# c-039 review — second independent reviewer

Reviewer: an independent review session. Tests run from the repo with uv (agents-service conftest provides the `client` fixture).

Gate results at HEAD (762f66d):
- agents-service api pytest: 115 passed, 1 failed, 4 errors (failure + errors are database-dependent tests unrelated to c-039: graph_restart, events, mailbox_race)
- test_internal_workflows.py: 2/2 PASSED

## 762f66d — feat(agents): other services read workflows and their owning team on an internal route

| Field | Value |
|---|---|
| check | 2/2 suite tests + 4 adversarial probes |
| result | PASSED |
| rule | A service (tools-service) needs to know which workflows exist and who owns them, to enforce that an approval request names a real workflow and that the right team decides it. New GET `/v1/internal/workflows` behind `service_principal` returns `[{id, name, owner, teamId, status}]`. Seeds use `team_ops` (Operations' dev id) instead of the placeholder `team_all`. |
| verdict | accept |
| defect | — |
| caveat | Registry not partitioned by tenant yet — the route serves all rows to any tenant-scoped service token. Docstring acknowledges this; tools-service keys its cache by tenant from the start. |

7 files, 260 ins / 4 del. Key changes:

- **`agent_registry.py`**: `SEED_TEAM = "team_ops"` constant. Agent seeds use `team_ops` instead of `team_all`.
- **`workflow_registry.py`**: imports `SEED_TEAM`; workflow `_row()` default team_id is now `team_ops`.
- **`schemas.py`**: `WorkflowRef(Out)` — id, name, owner, team_id, status.
- **`routers/workflows.py`**: `internal_router = APIRouter(prefix="/v1/internal", dependencies=[Depends(service_principal)])`. `internal_workflows()` reads all workflow rows, returns `[{id, name, owner, teamId, status}]`.
- **`app.py`**: mounts `workflows.internal_router`.
- **`openapi.json`**: `WorkflowRef` schema + `/v1/internal/workflows` GET route.
- **`test_internal_workflows.py`** (36 lines, 2 tests): (a) service reads every workflow, API-created ones keep their team, seeds name `team_ops` not `team_all`; (b) no auth, person dev token, and tenant-less service token are all refused.

## Probes — adversarial checks

### Probe 1a: person admin token is refused

A platform token with `kind: "person"`, `aud: ["agents"]`, and `roles: {team_ops: "admin"}` — an admin person — gets 401 on `/v1/internal/workflows`.

```
PROBE 1a: person admin token -> 401
```

### Probe 1b: service token with wrong audience is refused

A service token for `audience="platform"` (not `"agents"`) is refused.

```
PROBE 1b: wrong-audience service token -> 401
```

### Probe 1c: correct service token is accepted

A service token for `service="tools", audience="agents", tenant_id="local"` gets 200, returns a list of workflows all having `teamId` and `status`.

```
PROBE 1c: correct service token -> 200, N workflows, all have teamId and status
```

### Probe 1d: no workflow uses placeholder team_all

After the seed fix, no workflow in the list has `teamId == "team_all"`.

```
PROBE 1d: no workflow uses placeholder team_all
```

All 4 probes pass.

---

Gate results at c5ed407:
- tools-service pytest: 99/99 PASSED (after running migration 0008_approval_workflow_team on test DB)
- test_workflow_directory.py: 7/7 PASSED

## c5ed407 — feat(tools): workflow approvals read agents-service's workflows, and no runtime path reads tests/

| Field | Value |
|---|---|
| check | 7/7 suite tests + 4 adversarial probes |
| result | PASSED |
| rule | Tools-service stops owning workflow definitions. It reads them from agents-service's internal route (c-039 sha 1) via `AgentsWorkflows`, a 30s per-tenant cache that raises `ServiceUnavailable` on any failure — never an empty dict or stale guess. `request_approval` validates the workflow exists (400) and that its team has a local record (422, fail-closed). Approvals store `workflow_team_id` (migration 0008). `_owners` uses `team_by_id` on the recorded team. `_run_contexts` produces one sample context per workflow (caseId="sample", empty bindings). `call_row` gets workflow names from the approval record via `_workflow_names`, not a Directory lookup. Seeds move to `seed/tool_modules.json` with no workflows or runContexts. |
| verdict | accept |
| defect | — |
| caveat | The 31s sleeps in uc-041 (past the cache) make it ~2 min. Existing dev DBs keep `team_all` on seeded agent rows until `make up` rebuilds them. |

22 files, 3550 ins / 234 del. Key changes:

- **`modules/workflows.py`** (83 lines, new): `WorkflowRef` dataclass. `WorkflowDirectory` protocol. `AgentsWorkflows` — per-tenant 30s cache, `ServiceUnavailable` on failure (never empty). `StaticWorkflows` for tests.
- **`modules/service.py`** (+70/-30): `WorkflowDirectory` injected. `request_approval` validates workflow via `await self.workflows.all(tenant_id)` — unknown → 400, unknown team → 422. Approval stores `workflow_team_id`. `_owners` uses `team_by_id` on recorded team. `_run_contexts` produces sample contexts (one per workflow, caseId="sample", empty bindings). `_workflow_names` helper extracts names from approvals for `call_row`. `SAMPLE_CASE = "sample"` constant. Binding resolution gains sample-value path: when `ctx["caseId"] == SAMPLE_CASE`, the builder-typed arg value stands in with `source="sample"`.
- **`modules/directory.py`** (-14/+6): Removes `workflows`, `run_contexts`, `workflow_name`, `workflow_owner`. Adds `team_by_id(team_id)` — returns `None` for unknown ids (callers fail closed).
- **`modules/executions.py`** (-5/+5): `call_row` takes `names: dict[str, str]` (from `_workflow_names`) instead of `Directory`. Workflow name comes from the approval record.
- **`store/modules.py`** (+17): `workflow_team_id` column on `module_approvals`. `CHILD_DEFAULTS` generalized from `OPERATION_DEFAULTS` — approval rows written before the column get `None`.
- **`migrations/0008_approval_workflow_team.py`** (24 lines): adds nullable `workflow_team_id` column to `module_approvals`.
- **`modules/seed.py`** (-6): no longer loads `workflows` or `runContexts` from seed file.
- **`__main__.py`** (+8): wires `AgentsWorkflows` when agents-service URL configured; falls back to `StaticWorkflows`.
- **`settings.py`**: `tools_seed_file` default changed from `tests/fixtures/tool_modules.json` to `services/tools-service/seed/tool_modules.json`.
- **`tests/test_workflow_directory.py`** (136 lines, 7 tests): `FakeAgents` mock. Tests: real workflow accepted + decided by someone else, unknown workflow → 400, unknown team → 422 (fail-closed), stopped agents-service → 503, per-tenant cache isolation + expiry, sample run contexts, no settings default points into tests/.
- **`seed/tool_modules.json`** (2852 lines): production seed file — tool modules only, no workflows or runContexts.
- **`tests/fixtures/tool_modules.json`** (-295 lines): test fixtures slimmed; workflows and runContexts removed.
- **`export-console-seed.mjs`** (+25): writes both seed files; `teams.ts` gains `team_ops` and `team_security`.

## Probes — adversarial checks (sha 2)

### Probe 2a: cache isolation between tenants

`AgentsWorkflows` with two tenants returning different workflow lists. Tenant A gets only `wf_a_only`, tenant B gets only `wf_b_only`. Each tenant's call hits agents-service independently.

```
PROBE 2a: cache isolation — tenant A and B each got their own workflows, no cross-leak
```

### Probe 2b: stale cache for one tenant does not save another

Tenant A is cached, then agents-service goes down. Tenant B gets `ServiceUnavailable`. Tenant A is still served from cache.

```
PROBE 2b: tenant A cached, agents down — tenant B gets 503, tenant A still cached
```

### Probe 2c: SAMPLE_CASE constant

The `SAMPLE_CASE` constant is `"sample"` — sample contexts bind from the typed arg with `source="sample"`.

```
PROBE 2c: SAMPLE_CASE is 'sample' — sample contexts bind from the typed arg with source='sample'
```

### Probe 2d: call_row reads workflow name from the approval record

`call_row` with a `workflow:wf_test` subject resolves the name via `_workflow_names` (from the module's approval records), not a Directory method. The approval's `workflow_name: "My Custom Flow"` appears in the output.

```
PROBE 2d: call_row reads workflow name from the approval record, not a directory lookup
```

All 4 probes pass.

---

Gate results at 3f30c82:
- Code review only (1 console file, 4 ins / 2 del)

## 3f30c82 — fix(console): the module page's request-approval dialog takes useWorkflows

| Field | Value |
|---|---|
| check | code review |
| result | PASSED |
| rule | The request-approval dialog was wired to `lookups?.workflows` (the mock's fixture list). Now it reads from `useWorkflows({ page: 1, pageSize: 200 })`, the same hook the Workflows page uses — so it names the workflows agents-service actually has, not fixture placeholders. |
| verdict | accept |
| defect | — |
| caveat | `pageSize: 200` is a hard cap; a tenant with >200 workflows would not see them all in the dialog. Acceptable for now — no tenant is near that. |

---

Gate results at f31cb45:
- Code review only (1 make file + 1 doc, 13 ins / 2 del)

## f31cb45 — build(make): `make restart [SVC=]` runs alembic between stop and start

| Field | Value |
|---|---|
| check | code review |
| result | PASSED |
| rule | `make restart` was a bare `$(STACK) restart`, which started a service on code whose migration had not run (crashed on missing columns). Now it stops, migrates (each service's chain, or one with `SVC=`), then starts. Console is skipped (no database). `make/dev.mk` documents the gotcha in `docs/architecture/make.md`. |
| verdict | accept |
| defect | — |

---

Gate results at 32783c1:
- tools-service pytest: 103/103 PASSED (after all migrations applied)
- ops_identity pytest: 4/4 PASSED
- agents-service test_events: 5/5 PASSED (1 pre-existing database error)
- `grep -rn team_all services/*/src packages/*/src apps/console/src` → empty

## 32783c1 — fix(identity): ops_identity DEV_TEAM is team_ops, not team_all

| Field | Value |
|---|---|
| check | 103/103 tools + 4/4 identity + 5/5 events + grep verification |
| result | PASSED |
| rule | `DEV_TEAM` was `"team_all"`, a placeholder that no seed uses any more. Now `"team_ops"` — Operations, as platform-service's dev seed names it. `team_ops` scope changed from `"owned"` to `"all"` in teams.ts, seed/tool_modules.json, and test fixtures, matching platform-service's people.json (the dev user acts across teams). The `test_events::test_team_stream_follows_new_events` test was following `team_all` while threads landed in `team_ops` — fixed by importing `DEV_TEAM`. `grep -rn team_all` across all source directories is empty. |
| verdict | accept |
| defect | — |
| caveat | The scope `"all"` on team_ops means the dev user sees every module without an X-Team-Id header. `"owned"` would have hidden seeded modules (16 tests failed). This matches platform-service's intent: the dev user acts across teams. |

---

## Card-level verdict — c-039

**5 commits reviewed**: 762f66d, c5ed407, 3f30c82, f31cb45, 32783c1. All accepted.

**What the card delivers:**
- Workflow approvals name the workflows agents-service actually has, not fixture placeholders. Tools-service reads them from agents-service's new internal route (`GET /v1/internal/workflows`, service_principal guard) via `AgentsWorkflows`, a 30s per-tenant cache that raises `ServiceUnavailable` on any failure — never an empty list or stale guess.
- `request_approval` validates the workflow exists in agents-service (400 if unknown) and that its owning team has a local record (422, fail-closed). The approval stores `workflow_team_id` so visibility follows the team that owned the workflow at request time.
- Seeds use `team_ops` (Operations' dev id) instead of the placeholder `team_all`. `DEV_TEAM` in ops_identity is `team_ops`. `grep -rn team_all` across all source dirs is empty.
- `_run_contexts` produces one sample context per workflow (caseId="sample", empty bindings) — the builder types the bound values, marked as a sample. No runtime path reads `tests/`.
- `call_row` gets workflow names from the approval record, not a directory lookup.
- The console's request-approval dialog reads `useWorkflows` (agents-service's registry), not `lookups` (the mock's fixture list).
- `make restart` applies each service's alembic chain between stop and start, so a restart of newer code never meets a table without its new columns.

**Gate results across the card:**
- agents-service: 115 passed, 1 failed, 4 errors (all pre-existing database-dependent tests) at 762f66d; test_internal_workflows 2/2
- tools-service: 99/99 at c5ed407, 103/103 at 32783c1 (growing as migrations from other cards were applied)
- ops_identity: 4/4
- agents-service test_events: 5/5 (1 pre-existing database error)
- 8 adversarial probes across all shas: all passed (4 for sha 1 auth guard + cache + team_all elimination; 4 for sha 2 cache isolation + 503 propagation + SAMPLE_CASE + approval-sourced names)

walk repeated: approval request for a real workflow (dispute_email) → 201 with workflowName from agents-service; unknown workflow → 400 "Choose a workflow"; unknown team → 422 fail-closed; agents-service down → 503 workflows_unavailable; per-tenant cache isolation confirmed (tenant A's answer never served to tenant B); no team_all in source; console dialog reads useWorkflows not lookups

verdict: approve
