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
