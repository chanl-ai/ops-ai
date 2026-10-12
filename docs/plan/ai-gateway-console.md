# AI gateway in the console

Status: plan for review, nothing built.

Date: 2026-10-10. Owner: console and ai-gateway. Reads with [ADR-0008](../architecture/decisions/ai-gateway.md),
[spec 03](../specs/data-and-ai-gateways.md) sections 4.8 and 5.8 to 5.10, [spec 08](../specs/model-risk.md) and
[spec 09](../specs/governance-and-admin.md).

The console has no screen today for model providers, aliases, gateway keys, budgets or model-call activity.
Settings → Usage shows model cost per team and workflow for chargeback, and the agent page's model select lists
provider model names where spec 03 section 7 says it must list aliases. This plan adds one section of four pages
backed by the ai-gateway service, and says how it links to the pages that already exist.

## 1. What the feature is and is not

The AI gateway section is where the platform team, workflow owners, Security and Model Risk see and control
model egress: every request from a workflow, knowledge base, playground or eval run to a language or embedding
model. It covers four things.

| In scope | Owner of the data |
|---|---|
| Aliases (`bank-standard`, `bank-reasoning`, `bank-embed`) and their immutable versions, each mapped to a provider model, region and cleared sensitivity | ai-gateway (spec 03 4.8) |
| Provider connections: the provider or bank-hosted endpoint each alias version targets, with the vault reference for its credential | ai-gateway (new entity, section 6) |
| Gateway keys per workflow and environment, platform purpose keys and observe keys, with budgets and rotation | ai-gateway key-and-budget service (ADR-0008) |
| Model calls: the metadata log of every request, with no prompt or completion bodies | ai-gateway (spec 03 4.8, 5.8 rule 8.7) |

Out of scope, and where each lives instead:

| Out of scope | Lives in |
|---|---|
| Tool calls, module approvals, credentials for bank systems | tools-service; console Tools and Activity → Tool calls |
| Model inventory entries, risk tiers, validation, conditions, findings | Assurance → Model inventory (spec 08) |
| Chargeback by team and workflow | Settings → Usage (spec 09 4.9), which reads the same ledger |
| Prompt and completion bodies | The run journal, reached from the run trace |
| Suite runs triggered by an alias change | Assurance → Runs (spec 04) |

How the two model pages link. An inventory entry describes a use of a model (an agent, workflow or judge) and its
risk. An alias describes a model the bank has approved for traffic. The inventory entry's `alias` field
(spec 08 4.1) becomes a link to the alias page, and the alias page has a "Used by" tab listing the inventory entries
that pin it, with tier and validation status read from spec 08. Neither page stores the other's fields.

## 2. Prior art

Each product was read from its own documentation; one secondary source is marked.

| Product | Screens | Concepts | Fit for an in-bank deployment |
|---|---|---|---|
| Portkey | Model catalog (integrations, AI providers, models), configs, logs and traces, analytics, guardrails, prompts | Integration holds the provider credential once; an AI provider is a named slug over it with budget, rate limit and model allowlist per workspace; configs express retry, fallback and load balancing; logs record cache, retry and fallback state per request; "do not track" keeps only tokens, cost and latency | Open-source gateway self-hosts. Its own budget-limits page lists budgets as Enterprise or select Pro, which supports spec 03 D7 (our ledger is authoritative) |
| LiteLLM proxy UI | Virtual keys, models, teams and organisations, internal users, spend tracking, usage, logs, test chat | `max_budget` with `budget_duration`, soft-budget alerts, RPM and TPM limits, per-model budgets (enterprise), budget reservation for concurrent requests, model access groups | Self-hosted; the March 2026 supply-chain incident is in ADR-0008 |
| OpenRouter | Models, API keys, credits, activity, BYOK integrations, guardrails, private endpoints | Per-key credit limit with daily, weekly or monthly reset; expiry set at creation and fixed; disable a key; BYOK usage counted or excluded from the limit | Hosted service only |
| Cloudflare AI Gateway | Gateways, analytics, logs, provider keys, dynamic routes, settings | Requests, tokens, cost and errors per gateway; persistent logs with a quota; caching; rate limiting; retry and fallback; BYOK through an encrypted secrets store; custom costs for negotiated rates | Hosted edge service |
| Kong AI Gateway | Plugin configuration per route or service; dashboards in its cloud console | AI proxy, load balancing with failover, AI rate limiting by cost, prompt guard and semantic prompt guard, sanitizer for PII, semantic cache, prompt template and decorator, OpenTelemetry metrics | Self-hosted core; several AI plugins are Enterprise (ADR-0008, secondary) |
| Azure API Management AI gateway | Backends, policies per API, built-in monitoring dashboard | `llm-token-limit` (TPM and token quota per counter key), `llm-emit-token-metric` with custom dimensions, semantic cache store and lookup, weighted and priority load balancing, circuit breaker using `Retry-After`, content safety policy | Cloud-bound; noted for concepts only |

### Concepts a bank team needs

| Concept | Needed | Reason |
|---|---|---|
| Aliases that hide provider model names, versioned | Yes, phase 1 | A model change is a visible, testable event (spec 03 8.4) |
| Credential stored once per provider connection, referenced by vault path | Yes, phase 1 | Workers hold no keys (ADR-0004); rotation happens in one place |
| One key per workflow and environment, issued at publish | Yes, phase 1 | Cost and behaviour attribute to a registered identity |
| Monthly hard cap, per-run cap, alert at 80% | Yes, phase 1 | A runaway loop is capped; spec 03 8.6 |
| Budget ceiling by risk tier, above-ceiling change as a re-approval | Yes, phase 1 | Edit classes in spec 03 5.11 |
| Metadata-only request log with cache, retry and status per attempt | Yes, phase 1 | Audit and cost need it; bodies stay in the run journal |
| Cleared sensitivity per alias version | Yes, phase 1 | Requests above it are denied (spec 03 8.9) |
| Custom pricing per alias version | Yes, phase 1 | Bank contracts differ from list price; Usage shows cost in the bank's currency |
| Rate limits (requests or tokens per minute) per key | Later | Budgets and per-run caps bound phase 1 traffic; TPM matters once shared capacity is contested |
| Failover with evidence per alias | Later | Spec 03 5.9: only to targets with passing suite evidence |
| Redaction policy per sensitivity | Later, unless open question 13 of the overview says day one | Spec 03 5.9 |
| Discovery of unregistered model traffic | Later | Spec 03 5.10 |
| Credit balances and top-ups | No | The bank pays providers under contract; budgets express the limit |
| Semantic response cache | No in phase 1 | Spec 03 5.9 allows it only for deterministic operations at `internal` sensitivity or below |
| Prompt templates or decorators at the gateway | No | Prompts are versioned with the agent (ADR-0011); a gateway-side prompt would change behaviour outside the evidence |
| Log replay into a playground | No | Bodies are not in the gateway log; replay would need the run journal and a run-as context |
| Per-user personal keys | No | Callers are workflow and platform identities (ADR-0005) |

## 3. What the ADR and specs already require

| Requirement | Source | Covered by |
|---|---|---|
| Aliases with immutable versions: target, cleared sensitivity, capabilities, pricing | 03 4.8, M2, M3 | Models list and alias page, New version dialog |
| Callers name an alias; the gateway resolves the pinned version | 03 8.3 | Alias page, Pinned by tab |
| New alias version starts suite runs for every bound live workflow | 03 8.4, M3 | Alias page Versions tab shows run status with links to Assurance → Runs |
| Old alias versions stay served while pinned | 03 8.4 | Versions tab "Pinned by" count; Retire disabled with the reason while pinned |
| One key per workflow and environment, issued at publish, revoked at retirement | 03 8.5, M4, M5 | Keys and budgets list (no create for workflow keys) |
| Platform purpose keys for ingestion, playground, eval | 03 8.5, D8 | Keys and budgets, view Platform |
| Monthly hard cap, per-run cap, alert at 80%, tier ceiling | 03 4.8, 8.6, M6 | Key page Budget section |
| Budget above the tier ceiling creates a re-approval | 03 5.11, M6 `above_tier_ceiling` | Budget form submits a review to Reviews |
| Eval spend tracked per workflow in sub-ledgers | 03 4.8 | Eval key page, Sub-ledgers tab |
| Model call log fields, set by the gateway from the run context | 03 4.8, 8.7 | Model calls list and call sheet |
| Retries: at most 2, every attempt logged | 03 8.8 | Call sheet Attempts section |
| Sensitivity denial `sensitivity_not_cleared` | 03 8.9 | Model calls outcome facet, alias page header |
| Cache hit tokens reported per alias and workflow | 03 8.7, M7 | Alias page Traffic tab, key page stat card |
| Alias targets, cleared sensitivity, tier ceilings are locked to platform and Risk | 03 5.11 | Edit controls disabled with the reason for other roles |
| Alias versions and budget changes are audited | 03 8.2 | Audit log, linked from each page's History |
| Alias versions and budget at publish are workflow evidence | 03 8.3 | Evidence bundle in Assurance; alias version links to it |
| Agent model select lists aliases | 03 section 7 | Agent page select reads `aiGateway.aliases.options` |
| Usage per team and workflow reads M7 | 09 4.9, U1 | Settings → Usage, unchanged; links into keys |
| Tool-call log is one list over both gateways | 09 4.4 | Changed by this plan; see section 7 and open question 1 |
| Inventory entry shows the alias that serves it | 08 4.1 | Inventory entry links to the alias page; alias page Used by tab |
| Discovered agents and observe keys | 03 5.10, M8 | Later: Discovered view on Keys and budgets |

## 4. Placement in the nav

| Option | Who uses it | How often | What it sits near |
|---|---|---|---|
| A. Own item "AI gateway" under Govern | Platform team (aliases, providers), Security (keys, calls), Model Risk (alias evidence), workflow owners (their budget) | Platform weekly; owners when an alert fires; Security during investigations | Activity, Access, Assurance with Model inventory: the other oversight surfaces |
| B. Own item under Data Hub | The same people | The same | Connections and Tools, which are bank systems and content agents read; models would be the only non-data item |
| C. Tabs on Settings → Usage | Team admins reading chargeback | Monthly | Members, notifications, storage: per-team settings forms |

Recommendation: option A. Keys, budgets and the call log are controls and evidence, and Govern is where Activity,
Access and Assurance already hold the controls and evidence for tools and model risk. Data Hub groups what agents
read and the systems they read from, so models there would be the one item that is neither. Settings is per-team
and form-based, while aliases and providers are platform-wide records with versions and lists, so they would not
fit its layout or its audience.

The sidebar row is "AI gateway" (icon `IconCpu`), placed between Access and Assurance. Its title-switcher pages,
in order:

| Title-switcher page | Route | Nav entry |
|---|---|---|
| Models | `/ai-gateway` | parent, `tabTitle: 'Models'` |
| Keys and budgets | `/ai-gateway/keys` | child |
| Model calls | `/ai-gateway/calls` | child |
| Providers | `/ai-gateway/providers` | child |

Record routes: `/ai-gateway/models/[alias]`, `/ai-gateway/keys/[id]`, `/ai-gateway/providers/[id]`. A call opens in a
sheet with `?call=<id>`. `docs/console/page-plan.md` gains one nav row and one row per route.

## 5. Pages and dialogs

Every page uses `PageLayout` with `switcher` from `sectionFor`, `DataTableWithViews` with `SavedViewTabs`, server
pagination through `useListParams`, `StatCardGrid` above the table, and the designed states: `PageSkeleton` while
loading, `QueryError` with Try again, `ListEmpty` or `EmptyState` with the create action, filtered-empty with Clear
filters. Record pages use `RecordLayout` with `AttributeCard` and `FieldRow` in the rail and tabs in the main area.

Registry blocks and primitives checked in the shadcn registry: `dashboard-01` (stat cards, interactive area chart,
data table) is the layout the list pages already follow; `chart-area-interactive` for spend and calls over time;
`chart-bar-stacked` for spend by alias or by workflow; `progress` for budget meters; `item` was considered for the
provider list and rejected because the provider list needs facets and sorting. The console already has `ui/chart`,
`ui/progress`, `StatCard` and the usage panels, so no new primitive is added and `components/ui` is untouched.

### 5.1 Models (`/ai-gateway`)

Purpose: see every alias, which version is current, what it costs and who pins it.

| Element | Detail |
|---|---|
| Stat cards | Aliases, live versions pinned, model cost 30 days, calls denied 24h |
| Columns | Alias (name and kind: chat or embedding), current version, provider model, region, cleared sensitivity, pricing (input, output, cached per million), pinned by (workflows, knowledge bases), calls 24h, error rate 24h, suite status of the newest version |
| Saved views | All, Suite runs pending, Pinned old versions, Unused |
| Facets | Kind, provider, region, cleared sensitivity |
| Actions | New alias (header), New version (row menu, record page) |
| Row | Opens the alias page |

Alias page (`/ai-gateway/models/[alias]`). Rail: name, kind, current version, provider connection, region, cleared
sensitivity, capabilities, owner (platform). Tabs:

| Tab | Content |
|---|---|
| Versions | Every version with target, pricing, cleared sensitivity, created by, evidence reference, suite runs for bound workflows (passed, failed, running) linking to Assurance → Runs, pinned-by count; Retire disabled while pinned |
| Pinned by | Workflow versions, knowledge bases and eval, each with the version pinned and environment |
| Used by | Model inventory entries that resolve to this alias, with tier and validation status from spec 08 |
| Traffic | Calls, tokens, cost and cache hit rate over 30 days (`chart-area-interactive`), p95 latency, denials by reason |
| History | Audit entries for this alias |

Dialogs. New alias (`DialogShell` md, one screen): name and kind; it saves a draft alias with no version and opens
its page on the Versions tab. New version (`DialogShell` md): provider connection and provider model id are the
required fields; region, cleared sensitivity, capabilities and pricing are edited on the draft version before
Publish version, which confirms with "Starts suite runs for N live workflows". Designed states beyond the standard
ones: "No version yet" on a draft alias; "Suite runs pending" banner on a new version.

### 5.2 Keys and budgets (`/ai-gateway/keys`)

Purpose: see every gateway key, who owns it, and how close it is to its budget.

| Element | Detail |
|---|---|
| Stat cards | Keys active, over 80% of budget, at hard cap this month, denied for budget 24h |
| Columns | Owner (workflow and environment, or purpose such as `kb-ingest:<kb>`), kind (workflow, platform, observe), team, status (active, revoked), spent this month, hard cap, meter (`progress`, coloured at 80% and 100%), per-run cap, projected month end, tier ceiling, issued, last used |
| Saved views | All, Workflow keys, Platform, Near cap (80% and above), At cap, Revoked |
| Facets | Kind, team, environment, status |
| Actions | New purpose key (header, platform role only), Rotate, Revoke (row menu and bulk with `BulkConfirmDialog`) |
| Row | Opens the key page |

Workflow keys have no create action: the registry issues them at first publish and revokes them at retirement
(spec 03 8.5), and the empty state says so with a link to Workflows.

Key page (`/ai-gateway/keys/[id]`). Rail: owner, kind, team, environment, status, issued, last used, last rotated,
key id prefix. Main area:

| Section or tab | Content |
|---|---|
| Budget (`SettingsSection` with the unsaved bar) | Monthly hard cap, per-run cap, alert threshold, tier ceiling shown read-only; a value above the ceiling changes Save to "Request approval" and creates a review |
| Spend | Daily spend this month against the cap, spend by alias (`chart-bar-stacked`), cache hit rate |
| Sub-ledgers | Eval key only: spend per workflow |
| Calls | Model calls for this key, a filtered `DataTableWithViews` linking to Model calls |
| History | Rotations, revocations and budget changes from the audit log |

Dialogs. New purpose key (md, one screen): purpose (ingestion, playground, eval, observe) and the target it serves
(a knowledge base, or the runtime for observe); the budget is set on its page. Rotate (sm): states that the old key
stops working after the overlap window. Revoke (`DeleteDialog` with consequence text naming the workflow whose runs
will fail into the human step).

### 5.3 Model calls (`/ai-gateway/calls`)

Purpose: answer "what did this workflow, run or key send to which model, at what cost, and what happened".

| Element | Detail |
|---|---|
| Range | `date-range-picker`, default 24 hours |
| Stat cards | Calls, cost, p95 latency, denied (with the top reason) |
| Chart | Calls and cost per hour for the range (`chart-area-interactive`), computed by the API |
| Columns | Time, workflow and version (or purpose), agent and step, alias@version, provider model, input, output and cached tokens, cost, latency, attempts, outcome (`ok`, `error`, `denied` with reason), sensitivity, run (link) |
| Saved views | All, Denied, Errors, Slow (above p95), Retried, Budget denials |
| Facets | Alias, outcome, deny reason, workflow, key kind, team |
| Actions | Export CSV of the filtered set (server-side), no bulk actions |
| Row | Opens `ModelCallSheet` (`DetailSheet` with prev/next) |

The sheet shows the call's identity and run context, each attempt with status and latency, the resolved target,
the budget check result, and links to the run trace (the prompt and completion are there), the key, the alias
version and the tool calls of the same run. It shows no bodies.

### 5.4 Providers (`/ai-gateway/providers`)

Purpose: hold the connections alias versions point at: a hosted provider or a bank-hosted endpoint.

| Element | Detail |
|---|---|
| Stat cards | Connections, unhealthy, credentials expiring in 30 days |
| Columns | Name, type (hosted provider, bank-hosted, private endpoint), endpoint host, region, data residency, highest sensitivity it may receive, credential (vault reference and expiry), alias versions targeting it, health (last check, latency) |
| Saved views | All, Unhealthy, Credential expiring, Unused |
| Facets | Type, region, health |
| Actions | New provider connection (header), Test connection, Rotate credential reference |
| Row | Opens the provider page |

Provider page (`/ai-gateway/providers/[id]`): rail as the columns; tabs Settings (endpoint, region, residency,
sensitivity ceiling, credential reference as a form with the unsaved bar; all locked to platform and Risk), Alias
versions, Health (checks over 7 days), History.

New provider connection (md, one screen): name and type. It saves a draft and opens Settings; Test connection must
pass before any alias version can target it.

### 5.5 Who may do what

| Action | Role |
|---|---|
| Create alias, version, provider connection; retire a version | Platform, with Risk approval for cleared sensitivity (locked class, spec 03 5.11) |
| Change budget within ceiling | Workflow owner, platform (free edit, logged) |
| Change budget above ceiling | Request only; approved in Reviews |
| Rotate or revoke a key | Platform, Security |
| Read calls | Members for their team's workflows; platform, Security and Audit for all |

## 6. Contract

Layers follow `apps/console/CLAUDE.md`. The area is `aiGateway` and follows the console's per-area switch: mock
until the ai-gateway service is reachable through platform-service, then HTTP.

| Layer | File | Content |
|---|---|---|
| Types | `src/lib/types/ai-gateway.ts` | `Alias`, `AliasVersion`, `AliasDetail`, `ProviderConnection`, `GatewayKey`, `GatewayKeyDetail`, `Budget`, `BudgetInput`, `ModelCall`, `ModelCallDetail`, `ModelCallAttempt`, view and filter unions, `AliasOption` |
| Contract | `src/lib/api/ai-gateway-contract.ts` | `aiGateway.aliases.{list, get, create, createVersion, publishVersion, retireVersion, options}`, `aiGateway.providers.{list, get, create, save, test}`, `aiGateway.keys.{list, get, issuePurpose, rotate, revoke, bulkRevoke}`, `aiGateway.budgets.set`, `aiGateway.calls.{list, get, export}` |
| HTTP | `src/lib/api/ai-gateway-http.ts` | Routes below |
| Mock | `src/lib/api/mock/ai-gateway/` | Three aliases (chat standard, reasoning, embedding), one with a pending version; two providers (one hosted, one bank-hosted); keys for every mock workflow and environment plus ingestion, playground and eval keys, one at 85% and one at cap; 400 calls over 7 days with denials of each reason; `?mock=slow`, `error`, `empty` |
| Hooks | `src/hooks/ai-gateway-queries.ts` | `useAliases`, `useAlias`, `useCreateAlias`, `useCreateAliasVersion`, `usePublishAliasVersion`, `useAliasOptions`, `useProviders`, `useProvider`, `useTestProvider`, `useKeys`, `useKey`, `useRotateKey`, `useRevokeKeys`, `useSetBudget`, `useModelCalls`, `useModelCall` |

Routes ai-gateway serves (console traffic enters through platform-service, which adds the team scope):

| # | Route | Request | Response | Errors | Spec 03 row |
|---|---|---|---|---|---|
| 1 | `GET /v1/ai/aliases` | list params, `view`, filters | `ListResult<Alias> & { viewCounts, stats, facets }` | | M2, extended |
| 2 | `GET /v1/ai/aliases/{name}` | | `AliasDetail` with versions, pinned by, used by, traffic series | 404 | new |
| 3 | `POST /v1/ai/aliases` | `name`, `kind` | `Alias` (draft) | 409 name taken, 403 | new |
| 4 | `POST /v1/ai/aliases/{name}/versions` | `providerId`, `providerModel`, optional rest | `AliasVersion` (draft) | 403 `not_platform` | M3 |
| 5 | `POST /v1/ai/aliases/{name}/versions/{v}:publish` | | `AliasVersion` with started suite runs | 400 provider untested | M3 |
| 6 | `GET /v1/ai/aliases/options` | | `AliasOption[]` for the agent model select | | new |
| 7 | `GET /v1/ai/providers`, `GET /{id}`, `POST`, `PUT /{id}`, `POST /{id}:test` | | `ProviderConnection` | 403, 409 | new |
| 8 | `GET /v1/ai/keys` | list params, `view`, filters | `ListResult<GatewayKey> & { viewCounts, stats, facets }` | | new |
| 9 | `GET /v1/ai/keys/{id}` | | `GatewayKeyDetail` with budget, spend series, sub-ledgers | 404 | new |
| 10 | `POST /v1/ai/keys` | `purpose`, `target` | `GatewayKey` | 403 | M4 (purpose keys) |
| 11 | `POST /v1/ai/keys/{id}:rotate`, `POST /v1/ai/keys:revoke` | `ids[]`, `reason` | `GatewayKey`; `BulkResult` | 400 no reason | M5 |
| 12 | `PUT /v1/ai/budgets/{owner}` | `version`, `hardCap`, `perRunCap`, `alertAt` | `Budget`, or `{ reviewId }` above ceiling | 409 newer version | M6 |
| 13 | `GET /v1/ai/calls` | range, list params, `view`, filters | `ListResult<ModelCall> & { viewCounts, stats, series }` | | new, over 4.8 log |
| 14 | `GET /v1/ai/calls/{id}` | | `ModelCallDetail` with attempts and links | 404 | new |
| 15 | `GET /v1/ai/calls/export` | the list filters | CSV | | new |
| 16 | `GET /v1/ai/usage` | group by, range | as M7 | | M7, unchanged |

Derived server-side, never in a component: view counts, facet counts and stats on every list; spent, percentage of
cap, projected month end and status colour on keys; pinned-by and used-by counts; calls, error rate, p95 and cache
hit rate per alias and per key; hourly series for charts; deny-reason totals; the cost of each call from the alias
version's pricing at call time. The key secret is never returned; lists show an id prefix only.

## 7. Links to the rest of the console

| From | To | Link |
|---|---|---|
| Model inventory entry (spec 08) | Alias page | Alias field on the entry becomes a link; a workflow entry lists every alias its pinned agents use |
| Alias page Used by tab | Model inventory entry | Row link, tier and validation status shown read-only |
| Alias version | Assurance → Runs and Evidence | Suite runs started by the version; evidence bundles that pin it |
| Settings → Usage (spec 09) | Keys and budgets | A workflow row links to its key page; the page stays the chargeback report and reads the same ledger |
| Activity → Tool calls | Model calls | The call sheet links "Model calls in this run"; the model call sheet links "Tool calls in this run" by `runId` |
| Workflow Deployments and Settings tab | Key page | Each deployment's environment shows its gateway key status and budget meter, read from route 8 filtered by workflow |
| Workflow page | Key page | Cost column and budget per workflow (spec 03 section 7) link to the key |
| Agent page model select | Aliases | Options come from route 6, showing alias, current version and cleared sensitivity |
| Reviews | Key page | An above-ceiling budget review links to the key and shows current and requested caps |
| Audit log | Each record | Alias versions, budget changes, rotations and revocations are audit entries linking back |

## 8. Open questions with defaults

| # | Question | Default if nobody decides |
|---|---|---|
| 1 | Spec 09 4.4 puts model calls and tool calls in one Activity list. Should Activity → Tool calls keep `gateway: ai` rows? | Tool calls shows data gateway calls only; model calls have their own page because their columns differ; both sheets link by run. Spec 09 4.4 is amended |
| 2 | Is the section visible to every member or only to platform, Security, Risk and workflow owners? | Visible to all members, scoped to their team's keys and calls; aliases and providers are read-only outside platform |
| 3 | Does Providers ship in phase 1, or are provider targets fields on the alias version until there are several? | Phase 1, because cleared sensitivity and residency belong to the endpoint and are approved once per endpoint |
| 4 | Do keys get rate limits (requests or tokens per minute) in phase 1? | No; hard cap and per-run cap only. Add TPM per key when shared provider capacity is contested |
| 5 | Overlap window when a key rotates | 24 hours, during which both values are accepted |
| 6 | Who may change cleared sensitivity on an alias version? | Platform proposes, Risk approves through a review; versions are immutable, so a change is a new version |
| 7 | Does the eval key's budget count toward the workflow's Usage row? | No; Usage shows production spend, and the eval sub-ledger shows on the key page and in Assurance → Runs cost |
| 8 | Currency and pricing source | The bank's currency, from pricing on the alias version; the provider list price is not shown |
| 9 | Retention of the model call log in the console | 13 months online, matching the audit retention; older entries remain in the bank's log platform |
| 10 | Discovered agents (spec 03 5.10): a view on Keys and budgets or its own page? | A Discovered view on Keys and budgets when M8 ships, since observe keys are where discovered callers first appear |

## 9. Sources

| Source | Used for |
|---|---|
| [ADR-0008 AI gateway](../architecture/decisions/ai-gateway.md) | Day-one scope, key-and-budget service |
| [Spec 03 data and AI gateways](../specs/data-and-ai-gateways.md) | 4.8 entities, 5.8 to 5.11 rules, 6.5 operations, section 7 gaps |
| [Spec 08 model risk](../specs/model-risk.md) | Inventory entry and its alias field |
| [Spec 09 governance and admin](../specs/governance-and-admin.md) | Tool-call log, usage, API keys |
| [Console rules](../../apps/console/CLAUDE.md), [page plan](../console/page-plan.md), `apps/console/src/lib/nav.ts` | Components, layers, nav |
| [Portkey model catalog](https://portkey.ai/docs/product/model-catalog) | Integrations, AI providers, model provisioning |
| [Portkey budget limits](https://portkey.ai/docs/product/ai-gateway/virtual-keys/budget-limits) | Cost and token limits, reset periods, plan availability |
| [Portkey logs](https://portkey.ai/docs/product/observability/logs) | Log fields, cache and retry state, do-not-track |
| [LiteLLM proxy UI](https://docs.litellm.ai/docs/proxy/ui) | Screens |
| [LiteLLM budgets and rate limits](https://docs.litellm.ai/docs/proxy/users) | Budget duration, soft budgets, RPM and TPM, reservation |
| [OpenRouter key provisioning](https://openrouter.ai/docs/guides/overview/auth/provisioning-api-keys) | Credit limit, reset, expiry, BYOK counting |
| [Cloudflare AI Gateway](https://developers.cloudflare.com/ai-gateway/) | Analytics, logs, caching, rate limiting, fallback |
| [Cloudflare BYOK](https://developers.cloudflare.com/ai-gateway/configuration/bring-your-own-keys/) | Stored provider keys through a secrets store |
| [Kong AI Gateway](https://developer.konghq.com/ai-gateway/) | AI plugins and observability |
| [Azure API Management AI gateway](https://learn.microsoft.com/en-us/azure/api-management/genai-gateway-capabilities) | Token limit, token metrics, semantic cache, load balancing, circuit breaker |
| shadcn registry: `dashboard-01`, `chart-area-interactive`, `chart-bar-stacked`, `progress`, `item` | Blocks per surface |
