# Tools and MCP design

Status: current. Standard: `apps/console/CLAUDE.md`, `docs/ui/page-plan.md`, spec `03` §4.1–4.5,
[ADR-0005](../architecture/decisions/ADR-0005-identity-and-entitlement.md) (approval per major
version, policy approval tokens).

## What prior platforms did well

Two earlier internal products had tool screens worth reusing: an agent platform's HTTP tool editor,
and an MCP tool service's admin app. The "Where in this repo" column names the component that now
carries each pattern.

### Agent platform tool editor

| Strength | Where in this repo |
| --- | --- |
| HTTP operation builder: method and URL in one control, `{var}` path params listed as a typed table, headers, body template, timeout | `apps/console/src/components/tools/http-operation-builder.tsx` |
| Credentials only as `{{SECRET_NAME}}` references; a hard-coded `Authorization`/`X-API-Key` value raises a warning | same file |
| Secrets resolved in the template before model values are substituted, so a model value carrying a secret reference is sent literally | backend rule, spec `03` §5.4 |
| Test console: input form generated from the input schema, typed coercion, JSON validation per field, latency and raw response | `apps/console/src/components/tools/test-console.tsx` |
| Per-tool execution log beside the editor | `apps/console/src/components/tools/activity-panel.tsx` |
| Create flow starts with a type chooser; import from JSON is a peer of the types | `apps/console/src/components/tools/add-module-dialog.tsx` |

Weak spots not copied: one record per tool with no grouping by system, "toolsets" as a second grouping
the agent picks, `/new-*` pages, and no approval or expiry on access.

### MCP tool service admin

| Strength | Where in this repo |
| --- | --- |
| Catalog of apps as cards: logo, name, "N tools · auth kind", ownership chip, connected state | `apps/console/src/components/tools/catalog-grid.tsx` |
| Choose which operations to expose: grouped by resource, filter, "N of M selected", select all/none | `apps/console/src/components/tools/operation-picker.tsx` |
| Version diff: breaking changes first, added/removed/changed with field-level deltas | `apps/console/src/components/tools/versions-panel.tsx` |
| Re-sync an OpenAPI app: paste, upload or URL, result shown as the diff instead of a second picker | `apps/console/src/components/tools/versions-panel.tsx` |
| Secrets tab lists names only; values are never returned, so there is nothing to reveal | `apps/console/src/components/tools/credentials-panel.tsx` |
| Calls chart: successes and failures stacked over time, which shows when failures started | `apps/console/src/components/tools/activity-panel.tsx` |
| Approval policy per server, held calls reviewed in a queue | `apps/console/src/components/tools/approvals-table.tsx` |

Weak spots not copied: approval per server instead of per workflow, no expiry, no record binding.

## What we take

| From | Taken into Ops AI |
| --- | --- |
| Spec `03` | The **module** is the unit: one system, many operations, versioned (semver), security-reviewed once per major version, approved per workflow with mandatory expiry, record binding from run context, credentials as vault references, every call logged |
| MCP tool service admin | Catalog cards, operation picker for MCP discovery and OpenAPI import, view-changes diff, secrets by name, calls chart |
| Agent platform tool editor | HTTP operation builder, secret-reference warning, schema-generated test form with latency, per-module call log |
| Neither | Run-as context in the test console (which workflow's approval and which case's bound fields apply), masked output fields, four-eyes on money operations, deny reasons |

## Page plan

| Route | Purpose | Data |
| --- | --- | --- |
| `/tools` tab **Modules** | One row per module: type, version, operations, access classes, approval state and next expiry, workflows, 24h calls and error rate. Views: All, Needs approval, Expiring soon (30 days), Failing. Facets: type, access, approval | `useToolModules` → `toolModules.list` (stats, view counts, facets from the API) |
| `/tools` tab **Catalog** | Bank catalog of known systems as cards; Add opens the add dialog prefilled | `useToolCatalog` |
| Add module (dialog, 3 steps) | Source (MCP URL, OpenAPI URL or file, HTTP operation, code disabled) → Operations (picker from discovery, access class per operation; HTTP builder for HTTP) → Review. Creates a draft and opens its page | `useDiscoverModule`, `useCreateModule` |
| `/tools/[id]` **Operations** | Table of operations; sheet per operation: access class, input schema viewer, record binding, rate limit, requires approval, four-eyes, amount limit. Edits stage an unpublished version | `useToolModule`, `useUpdateOperation`, `usePublishModuleVersion` |
| **Test console** | Pick operation, run-as context (workflow and case), stub or sandbox, form from the schema, bound fields shown read-only, response with masked fields, gateway decision and latency | `useTestModule` |
| **Access** | Approvals per workflow: operations, environment, expiry, status; request, approve/reject (owner team, not the requester), revoke with reason; link to `/access` | `useRequestApproval`, `useDecideApproval`, `useRevokeApprovals` |
| **Approval** | Security reviews bound to the major version, request re-review, current major's findings | `useRequestReview` |
| **Credentials** | Vault references per environment, kind, rotate-by date and status; change the reference; values never shown | `useSetCredentialRef` |
| **Activity** | 14-day calls chart (ok vs failed), p95 latency, denied calls, recent calls linking to `/logs/tool-calls?q=` | `useModuleActivity` |
| **Versions** | Versions with major/minor, status, pinned workflows, reachability; View changes dialog | from `useToolModule` |

Agents still grant operations (`Tool`). Grants show `Module · operation`, group by module in the grant
dialog, and money operations state the four-eyes rule.

## Deviations from the brief

| Deviation | Reason |
| --- | --- |
| Access and Approval are separate tabs | Spec `03` separates them: the security review approves a module's major version once; workflow approvals grant operations with expiry. Merging them hides which one lapsed |
| Code modules appear in the add dialog disabled ("Code modules need the sandbox, planned after phase 1") | No sandbox exists in phase 1 |
| Module approvals on `/tools/[id]` and grants on `/access` are separate mock stores seeded from the same catalogue | A real backend serves both from one approvals table |
