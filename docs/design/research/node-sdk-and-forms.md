# Node SDK and node forms: prior art

Status: research note; sources as read in October 2026. The "What Ops AI had at the time" section is a snapshot: since then
node types have gained UI hints and the console renders node forms (`packages/ops_engine/src/ops_engine/node_types.py`,
`apps/console/src/components/workflows/definition-editor/node-form.tsx`).

How should a workflow platform let people add node types, and how should each node's settings be edited? Ops AI's
workflow engine is layered: a core engine, a Node SDK every node implements, node packs installed at deploy time from
reviewed packages, and triggers as adapters on one start-run API. Every node setting is a form; a type gets a generated
form by default and may ship a custom form. This note studies how n8n, Node-RED, Windmill, Pipedream and Zapier define
nodes, forms, credentials and triggers, what went wrong for them, and recommends a Node SDK contract and a trigger
adapter contract.

Repo paths are in the Ops AI repository; everything else is cited by URL or upstream repo path. Statements marked
"inference" are conclusions drawn from the cited material; everything else is stated by the source.

## What Ops AI had at the time

| Area | State | Evidence |
|---|---|---|
| Type registry | `NodeType` dataclass: `id`, integer `version`, `group`, `label`, `description`, `executor` (a string key), `effects` (none, model, read, write, human), `inputs`/`outputs` ports with a connection type, `parameters` as JSON Schema, `outputs_from` (ports derived from a list parameter), optional `retry`, `timeout_seconds`. Registry keyed by `(id, version)`; duplicate registration raises | `packages/ops_engine/src/ops_engine/node_types.py:56-140` |
| Retry by effects | none 3, read 3 with backoff, model 2, write 1 plus reconciliation, human 1 | `node_types.py` `RETRY_BY_EFFECTS` |
| Built types | seven: `ops.trigger.request`, `ops.data.set`, `ops.flow.if`, `ops.action.tool`, `ops.ai.agent`, `ops.flow.humanReview`, `ops.flow.end` | `node_types.py` `BASIC_TYPES` |
| Parameter schemas | plain JSON Schema with `description` text; mapping fields are untyped values whose description says "a value, or a path `$.input.<field>` or `$.nodes.<id>.out.<field>`". No UI hints, no option sources: `agent` and `operation` are free strings | `node_types.py` `_MAPPING`, `ops.ai.agent`, `ops.action.tool` |
| Executors | module-level async functions taking a `NodeCall` and returning an `Outcome` (`trigger_payload`, `data_set`, `flow_if`, `gateway_call`, `review_open`, `kernel_turn`, `flow_end`); a `Wrapper` applies journal, recorded-output return, retry and reconcile around each | `packages/ops_engine/src/ops_engine/compiler.py:111-420` |
| Ports to the outside | `ToolPort` (call with key run:node:iteration:attempt and fencing generation, access class, mint approval token, find for reconcile), `ReviewPort`, `AgentPort`, `FilesPort`, `TimerPort`, `RunPort`, `KnowledgePort`, `StepHooks` | `packages/ops_engine/src/ops_engine/ports.py` |
| Editor | node inspector edits parameters as a raw JSON textarea; only parse errors are caught client-side, the schema check is the server's | `apps/console/src/components/workflows/definition-editor/node-inspector.tsx:106-117` |
| Old v1 palette | `NODE_KINDS` with per-kind `fields: FieldSpec[]` (`key`, `label`, `input`: text, textarea, select, branches; `options`: an `OptionSource` such as agents, tools, collections, workflows, owners, reviewerGroups, sla, durations, schedules); most fields write to one `description` key | `apps/console/src/components/workflows/node-types.ts:45-118` |
| Agreed design | type fields table says `parameters` is "JSON Schema with UI hints" and that editor, validator and runner all read the registry; 22 new and 14 changed types listed | [workflow nodes](../workflows/workflow-nodes.md) |
| Lesson from Forge | Forge's registry claimed "compiler, validator and palette read from this registry without edits", but per-type facts sat in five other places and drifted (inspector help text describing the wrong expression language; a factory reading a field its schema lacked). The type must own every fact other layers need | [Forge study, "How a node type is defined and added"](forge-workflow-study.md#how-a-node-type-is-defined-and-added) |

Gaps against the layered design: no form model (UI hints, widgets, conditions, option sources), no SDK boundary
(executors are engine functions selected by string), no pack format or install path, no credential declaration, no
trigger adapter contract, no per-type test harness.

## n8n

Source: `n8n-io/n8n` at `ec074519` (2026-10-16), paths below relative to that repo; docs at docs.n8n.io.

### Node contract

A node is a TypeScript class implementing `INodeType`: a `description: INodeTypeDescription` plus at most one way of
running (`packages/workflow/src/interfaces.ts:2594-2656`).

| Member | Purpose |
|---|---|
| `execute(this: IExecuteFunctions)` | programmatic action node; returns `INodeExecutionData[][]`, one array per output |
| `poll(this: IPollFunctions)` | polling trigger; the engine calls it on the node's schedule; `null` means nothing new |
| `trigger(this: ITriggerFunctions)` | long-lived trigger (a socket, a queue consumer); returns a close function |
| `webhook(this: IWebhookFunctions)` plus `webhookMethods.{checkExists,create,delete}` | webhook trigger, with lifecycle hooks that register and remove the webhook at the third party when the workflow is activated and deactivated (`interfaces.ts:2559`, `2633-2637`) |
| `supplyData` | sub-node that supplies a model, tool or memory to an AI root node |
| `methods.loadOptions`, `listSearch`, `resourceMapping`, `credentialTest`, `actionHandler` | editor-time functions the form calls: dropdown options, searchable lists with pagination, column mapping, credential test, button actions |
| `customOperations` | code for one resource/operation pair on an otherwise declarative node |

The description carries `name`, `displayName`, `group`, `version` (a number or an array), `defaults`, `inputs` and
`outputs` (connection types, or an expression that computes them from parameters), `properties`, `credentials`,
`polling`, `webhooks`, `requestDefaults`, `hints`, `usableAsTool`, `sensitiveOutputFields` and more
(`interfaces.ts:2851-2912`, `3147-3200`). The `this` context of every function is the engine's: parameters, credentials,
HTTP helpers, binary data and static data all come through it, so the class never imports the engine.

### Declarative and programmatic styles

Declarative nodes have no `execute`. Each property may carry `routing` (`INodePropertyRouting`,
`interfaces.ts:2915`) that says how its value becomes part of an HTTP request (query, body, header, URL) and how the
response is post-processed; `requestDefaults` sets the base URL. The engine builds and sends the request. n8n
recommends declarative for new REST nodes because it "uses a JSON-based syntax, making it simpler to write, with less
risk of introducing bugs" and "is more future-proof", and requires programmatic for every trigger, non-REST APIs,
item-wise transformation and feature-flag versioning
([choose a node method](https://docs.n8n.io/integrations/creating-nodes/plan/choose-node-method/)).

Inference: declarative nodes are the closest n8n gets to "nodes reach the outside only through engine ports": a
declarative node never opens a socket itself, the engine does. Programmatic nodes run arbitrary code in the n8n
process.

### Properties and the form

Every setting is an `INodeProperties` entry (`interfaces.ts:2192-2245`): `displayName`, `name`, `type`, `default`,
`required`, `description`, `hint`, `placeholder`, `options`, `typeOptions`, `displayOptions`, `disabledOptions`,
`noDataExpression`, `validateType`, `routing`, `modes` (for resource locators). The property list is the form; there is
no separate UI schema.

| Feature | How it works | Evidence |
|---|---|---|
| Field types | `string`, `number`, `boolean`, `options`, `multiOptions`, `dateTime`, `color`, `json`, `collection`, `fixedCollection`, `resourceLocator`, `resourceMapper`, `filter`, `assignmentCollection`, `credentialsSelect`, `workflowSelector`, `agentSelector`, `notice`, `callout`, `button`, `hidden`, `curlImport` | `interfaces.ts:1951-1975` |
| Show and hide | `displayOptions.show` / `hide` map another parameter's name to the values that show or hide this one; `@version` keys a field to node versions, `@tool` to tool use, `@feature` to feature flags; `DisplayCondition` allows operators beyond equality | `interfaces.ts:2157-2172` |
| Resource and operation | the convention for API nodes: an `options` field `resource`, an `options` field `operation` shown per resource, then fields shown per operation. It is a convention built with `displayOptions`; the engine has no resource or operation concept | `packages/nodes-base/nodes/Github/Github.node.ts:118`, `167` |
| `collection` | an "Add option" bag of optional fields | `ParameterInputList.vue:870-941` |
| `fixedCollection` | named groups of repeating rows (headers, conditions) | `ParameterInputList.vue:909` |
| Dynamic options | `typeOptions.loadOptionsMethod` names a function in `methods.loadOptions`; `loadOptionsDependsOn` lists parameters whose change reloads the list; declarative nodes can use `typeOptions.loadOptions.routing` instead | `interfaces.ts:2035-2037`, `ParameterInput.vue:363`, `606-621` |
| Resource locator | one field with modes (from list via `listSearch`, by URL, by ID), each with its own validation and extraction | `interfaces.ts:2246-2280`, `ResourceLocator/ResourceLocator.vue` |
| Expressions | any value string starting with `=` is an expression (`={{ $json.email }}`), evaluated at run time; `noDataExpression` forbids it on a field; `allowArbitraryValues` skips the check that an options value is in the list, for values that come from an expression | `packages/workflow/src/expressions/expression-helpers.ts:1-9`, `interfaces.ts:2216-2236` |
| Shared visibility logic | `displayParameter`, `getNodeParameters` and `getNodeParametersIssues` live in the shared `n8n-workflow` package, so the editor and the backend apply the same show/hide and required rules | `packages/workflow/src/node-helpers.ts:419`, `773`, `1363` |

The editor renders the form from the description: `ParameterInputList.vue` walks `properties`, drops those whose
`displayOptions` do not match, and hands each to `ParameterInput.vue`, which picks a widget by `type`
(`packages/frontend/editor-ui/src/features/ndv/parameters/components/`). Inference from the code and the absence of any
component hook in `INodeTypeDescription`: a community node cannot ship its own editor component. Every richer widget
(resource mapper, filter, assignment collection, agent selector) was added to core as a new property type.

### Credentials

A credential type is an `ICredentialType` (`interfaces.ts:427-480`): its own `properties` (rendered by the same form
engine), `authenticate` (how to apply the secret to a request, declaratively), `preAuthentication` (fetch a session
token), `test` (a request plus success rules), `extends` (OAuth2 base types), `supportedNodes` and
`restrictToSupportedNodes`, which makes the engine "refuse to decrypt the credential for any other node — including
the HTTP Request node" (`interfaces.ts:464-472`). A node lists the credential types it accepts in
`description.credentials` with `displayOptions` and `testedBy` (`interfaces.ts:2783-2790`). Secrets are stored
encrypted with the instance key and decrypted in-process when a node asks for them.

### Triggers

Three trigger shapes: `poll` with `polling: true` (the engine owns the schedule; the node stores its cursor in
`getWorkflowStaticData`, `interfaces.ts:1201`), `webhook` with `webhooks` descriptions and lifecycle methods, and
`trigger` for long-lived listeners. Dedupe is the node's job: each poll node keeps its own last-seen id or timestamp in
static data. Inference: there is no engine-level dedupe key on a run start.

### Versioning

Light versioning: `version: [1, 1.1, 2]` on one class, with `displayOptions.show['@version']` to vary fields. Full
versioning: a `VersionedNodeType` (`IVersionedNodeType`, `interfaces.ts:2766-2773`) mapping each version to its own
class, with `defaultVersion`; not available for declarative nodes. "If a user builds and saves a workflow using version
1, n8n continues to use version 1 in that workflow, even if you create and publish a version 2"; new workflows get the
latest ([node versioning](https://docs.n8n.io/integrations/creating-nodes/build/reference/node-versioning/)). Packages
also declare `n8n.n8nNodesApiVersion` in `package.json`, checked against the instance's supported level
(`packages/workflow/src/nodes-api-version.ts`).

### Tooling, distribution and trust

| Piece | What it does | Evidence |
|---|---|---|
| `@n8n/node-cli` (`n8n-node`) | `new` (templates: declarative or programmatic), `dev` (links the package into a local n8n with hot reload), `build`, `lint`, `release` | `packages/@n8n/node-cli/README.md`, `src/commands/` |
| Community packages | npm packages named `n8n-nodes-*`, installed from the UI or CLI at runtime into the instance | `packages/cli/src/modules/community-packages/` |
| Verified nodes | n8n vets packages and stores a checksum per version; in verified-only mode (`N8N_UNVERIFIED_PACKAGES_ENABLED=false`) install takes version and checksum from the vetted list and fails when npm's `dist.integrity` does not match | `community-packages.config.ts:23-29`, `community-packages.lifecycle.service.ts:67-91`, `npm-utils.ts:297-329` |
| Verification rules | no runtime dependencies, MIT licence, published from GitHub Actions with provenance (required from 2026-05-01), `npx @n8n/scan-community-package` passes, no environment or file system access, public repo matching the npm metadata | [verification guidelines](https://docs.n8n.io/integrations/creating-nodes/build/reference/verification-guidelines/) |
| Kill switches | `N8N_COMMUNITY_PACKAGES_ENABLED`, `N8N_COMMUNITY_PACKAGES_PREVENT_LOADING`, `N8N_COMMUNITY_PACKAGES_REGISTRY` | `community-packages.config.ts` |

### Where it hurts

| Problem | Evidence |
|---|---|
| Community nodes run in-process with full rights: they "have full access to the machine that n8n runs on, and can do anything, including malicious actions" and "access to data in your workflows" | [community node risks](https://docs.n8n.io/integrations/community-nodes/risks/) |
| January 2026: eight npm packages posing as n8n integrations (27,000 downloads) prompted users to link accounts and, once installed, decrypted stored OAuth tokens with the instance key and sent them out | [The Hacker News, 2026-01](https://thehackernews.com/2026/01/n8n-supply-chain-attack-abuses.html) |
| Expressions are JavaScript evaluated in the server; CVE-2025-68613 (CVSS 9.9) let an authenticated workflow editor run arbitrary code through an expression | [GitLab advisory](https://advisories.gitlab.com/pkg/npm/n8n/CVE-2025-68613/) |
| Breaking changes: a node update can "cause all workflows using the node to break" when the author does not version it | [community node risks](https://docs.n8n.io/integrations/community-nodes/risks/) |
| Form power grows only in core: each new widget is a new property type in `NodePropertyTypes`, and the property type list now has 24 entries, several of which (`resourceMapper`, `filter`, `assignmentCollection`) are complete sub-editors | `interfaces.ts:1951-1975` |
| Dedupe and cursors are per node in static data, so each polling node reimplements them | `interfaces.ts:1201` (inference from the API shape) |

Lessons for Ops AI: the description-is-the-form model works at scale (hundreds of nodes, one renderer); visibility rules
belong in shared code that the server also runs; credentials should be bound to the node types allowed to use them;
the in-process, runtime-installed package model is the main source of n8n's security incidents.

## Node-RED

Source: nodered.org documentation, "Creating nodes" section.

### Node contract

A node is two files in an npm package listed under `node-red.nodes` in `package.json`
([packaging](https://nodered.org/docs/creating-nodes/packaging)):

| File | Contents |
|---|---|
| `.js` (runtime) | a constructor that receives the editor-set properties, calls `RED.nodes.createNode(this, config)`, registers `on('input', (msg, send, done) => …)` and `on('close', …)`, reports with `this.status(…)`, and passes errors to `done(err)` so Catch nodes see them ([JavaScript file](https://nodered.org/docs/creating-nodes/node-js)) |
| `.html` (editor) | `RED.nodes.registerType(type, { category, defaults, credentials, inputs, outputs, label, oneditprepare, oneditsave, oneditcancel, oneditresize })`, a `<script type="text/html" data-template-name="<type>">` holding the hand-written dialog, and a help template |

### Form definition

The dialog is hand-written HTML. Each property in `defaults` is bound to the element with id
`node-input-<propertyname>` (`node-config-input-<name>` for config nodes); the `oneditprepare`, `oneditsave` and
`oneditcancel` hooks set up and tear down custom widgets
([edit dialog](https://nodered.org/docs/creating-nodes/edit-dialog)). `defaults` entries carry `value`, `required`,
`validate` (a function, or `RED.validators.number()` / `regex()`) and `type` (a pointer to a config node), and "the
editor attempts to validate all properties to warn the user if invalid values have been given"
([properties](https://nodered.org/docs/creating-nodes/properties)). The docs describe validation only in the editor;
inference: the runtime does not re-check property values, so a flow file edited outside the editor reaches the node
unvalidated.

The `TypedInput` widget is Node-RED's answer to expression fields: one input plus a type selector (`msg`, `flow`,
`global`, `str`, `num`, `bool`, `json`, `jsonata`, `env`, `cred`, …), with the chosen type stored in a sibling property
named by `typeField` ([TypedInput](https://nodered.org/docs/api/ui/typedInput/)). Storing value and kind side by side
avoids n8n's `=` prefix convention.

### Credentials and config nodes

`credentials` entries are `text` or `password`; they are "stored separately to the main flow file and do not get
included when flows are exported", and password values never reach the editor, which sees only `has_<name>`
([credentials](https://nodered.org/docs/creating-nodes/credentials)). Shared connections (a broker, a database) are
config nodes referenced by a `type` pointer in `defaults`.

### Triggers, versioning, distribution

No trigger contract: an input node is a node with no inputs that calls `send` when its own listener fires. No per-node
version on the instance; a flow stores the type name only, so an npm upgrade changes every flow that uses the node
(inference from the flow format, which has no version field). Packages are installed from npm through the palette
manager; the Flow Library indexes them on manual submission and shows a scorecard
([packaging](https://nodered.org/docs/creating-nodes/packaging)). Nodes run in the Node-RED process with its rights.

### Lessons

Total freedom in the dialog (arbitrary HTML and jQuery) makes every node look and behave differently, and the
editor-only validator leaves the runtime trusting stored values. The parts worth copying: write-only password
credentials with a `has_<name>` flag, and the TypedInput pattern that stores the value kind explicitly.

## Windmill

Source: windmill.dev documentation.

### Node contract

A node is a script: a `main` function in TypeScript, Python, Go, Bash, SQL and others. "Each parameter in the main
function of a script corresponds to a field in the JSON Schema"; Python `str`, `int`, `float`, `bool` map to `string`,
`integer`, `number`, `boolean`, and TypeScript types map the same way
([JSON schema and parsing](https://www.windmill.dev/docs/core_concepts/json_schema_and_parsing)). The return value is
the step's result. There is no separate description object: the signature is the contract, and the inferred schema is
stored with the script.

### Form definition

The generated form comes from the inferred JSON Schema. Authors adjust it in the "Generated UI" menu: title,
placeholder, password fields, enums, file uploads, currency formatting. Dynamic dropdowns use a `DynSelect_<name>`
type plus a function that computes options from other inputs. Typed references to workspace resources use
`resource-<type>` formats, so a field typed `Stripe` becomes a picker of Stripe resources
([JSON schema and parsing](https://www.windmill.dev/docs/core_concepts/json_schema_and_parsing)).

Inference: schema-from-signature removes the drift Forge suffered (one source for the runner and the form), at the cost
of putting form hints into a side channel the signature cannot express.

### Data mapping

Each step input is either a static value or a "JavaScript expression that operates in a more restricted setting" over
`flow_input` and `results.<step id>`, with a quick-connect button when the mapping is one-to-one
([flow architecture](https://www.windmill.dev/docs/flows/architecture)). Retries, caching, and suspend-for-approval are
per-step flow settings that live on the flow step; the script does not declare them ([flow editor](https://www.windmill.dev/docs/flows/flow_editor)).

### Credentials

Resources are typed JSON objects whose resource type is a JSON Schema; secrets live in variables and a resource holds
a `$var:` reference "resolved at fetch time", so only the reference is stored in the resource
([resources and types](https://www.windmill.dev/docs/core_concepts/resources_and_types)).

### Triggers

Triggers (schedule, webhook, HTTP route, email, Kafka, NATS, Postgres, SQS, MQTT, websocket, MCP tool calls) start any
script or flow. A preprocessor normalises the raw event first: it receives an `event` that "always contain[s] a `kind`
field that contains the type of trigger", with trigger-specific fields such as `body`, `raw_string`, `query`, `headers`
for a webhook ([preprocessors](https://www.windmill.dev/docs/core_concepts/preprocessors)). Keeping `raw_string`
allows signature checks over the exact bytes received.

### Versioning and distribution

"Versions of Scripts are uniquely defined by their hashes. They are an immutable reference similar to a git commit
SHA"; deploying to a path makes a new head and the previous one stays "deployed forever"
([versioning](https://www.windmill.dev/docs/core_concepts/versioning)). Distribution is the Windmill Hub plus workspace
sync from git. Inference: script forms have no per-script custom renderer; the Generated UI settings are the only
adjustment, and Windmill's app builder is a separate product for custom screens.

### Lessons

Windmill's generic trigger-plus-preprocessor split is the model for "triggers as adapters on one start API". Content
hashes give exact pinning for audit. Schema-from-signature suits user-written scripts; Ops AI's node packs need richer
form hints than a signature carries, so the schema should be declared, with a test that the executor's input model
and the declared schema agree.

## Pipedream components

Source: pipedream.com component documentation.

| Aspect | What Pipedream does | Evidence |
|---|---|---|
| Contract | a JavaScript object: `key`, `name`, `version`, `type` (`"action"`, or omitted for a source), `props`, `methods`, `hooks` (`deploy`, `activate`, `deactivate`), `run` | [component API](https://pipedream.com/docs/components/contributing/api) |
| Form | `props` is the form: `string`, `integer`, `boolean`, `object`, `any`, with `label`, `description`, `optional`, `secret`, `options`; `propDefinitions` on an app file let many components reuse one prop (a "channel" picker shared by every Slack action) | same |
| Dynamic options | `options({ page, prevContext, query })` returns the choices with pagination and search | same |
| Dynamic fields | a prop with `reloadProps: true` makes the platform call `additionalProps()` to compute the remaining props from the chosen values | same |
| Credentials | an app prop `{ type: "app", app: "slack" }` binds a managed connected account; the component reads `this.<app>.$auth`; secrets never appear as plain props | same |
| Engine-provided services | `$.interface.timer` (schedule), `$.interface.http` (an HTTP endpoint with `respond()`), `$.service.db` (key-value state) are props the platform injects | same |
| Triggers | sources emit events with `this.$emit(event, { id, summary, ts })`; dedupe strategies `unique` (last 100 ids), `greatest` (highest id), `last` are declared on the component and applied by the platform from the `id` | same |
| Webhook lifecycle | "a common use case for the deploy hook is to create webhook subscriptions when the source is deployed"; `deactivate` removes them | same |
| Run output | actions get `$` with `$.export()` for named outputs and `$.summary` for a one-line human summary of what the step did | same |
| Versioning | semantic versions; a changed shared file means bumping "all components that import or are affected by the updated file" | [guidelines](https://pipedream.com/docs/components/contributing/guidelines) |
| Distribution and trust | registry components arrive as pull requests to `PipedreamHQ/pipedream`, run through automated checks, and are reviewed before publishing; private components deploy with the CLI to one account | [guidelines](https://pipedream.com/docs/components/contributing/guidelines) |

Lessons: the platform-declared dedupe strategy keyed on an event id is the cleanest trigger dedupe contract among the
platforms read here. `propDefinitions` and `$.summary` are two small ideas worth copying: shared field definitions per
pack, and a summary line every step must produce for the run view and audit log.

## Zapier Platform CLI

Source: docs.zapier.com.

| Aspect | What Zapier does | Evidence |
|---|---|---|
| Contract | an `App` object: `authentication` (with a `test`), `triggers`, `searches`, `creates`; each has `operation.inputFields` and `operation.perform(z, bundle)` | [CLI overview](https://docs.zapier.com/platform/build-cli/overview) |
| Form | `inputFields` entries: `key`, `label`, `type` (string, text, code, integer, number, boolean, datetime, file, password, copy, json), `required`, `choices`, `helpText`, `children` (line items), `dynamic`, `search`, `altersDynamicFields`, `group`, `schema` for json fields | [input fields](https://docs.zapier.com/platform/build-cli/input-fields) |
| Dynamic fields | an entry in `inputFields` may be a function `(z, bundle) => fields`; a field marked `altersDynamicFields` re-runs those functions on change | same |
| Run | `perform` reads `bundle.inputData` and `bundle.authData`; HTTP goes through `z.request`, which applies auth | [CLI overview](https://docs.zapier.com/platform/build-cli/overview) |
| Triggers | polling (`perform` returns a list, newest first) or REST hooks (`performSubscribe`, `performUnsubscribe`); the platform dedupes on `id`, or on output fields marked `primary` | same |
| Versioning | every integration version is immutable and private until `zapier promote`; `zapier migrate` moves users between versions; `zapier deprecate` warns them | same |
| Checks | `zapier validate` (structure) and `zapier test` (local tests) before push | same |

Lessons: platform-owned dedupe on a declared primary key; explicit promote and migrate commands so a version change is a
reviewed, recorded act; installing a package never changes the version a workflow runs.

## Temporal and Inngest (effects and idempotency only)

| Platform | What it says | What it means for the Node SDK | Evidence |
|---|---|---|---|
| Temporal | "Activities may be retried, these functions may be executed more than once"; a worker that finishes an activity and crashes before reporting causes a retry; recommends "a combination of the Workflow Run ID and the Activity ID as an idempotency key" passed to the external service | The engine supplies the key; the node passes it to the outside. Ops AI already does this with run:node:iteration:attempt on `ToolPort.call` | [activity definition](https://docs.temporal.io/activity-definition) |
| Inngest | an event `id` "acts as an idempotency key over a 24 hour period"; a function-level `idempotency` key is a CEL expression over the event payload; steps should "send a stable operation key" to payment, email or database APIs because "a request can succeed before Inngest records the step result" | Trigger dedupe belongs on the start API (event id, or a key expression declared by the trigger), with a stated window; step-level keys cover the gap between the effect and the journal write | [handling idempotency](https://www.inngest.com/docs/guides/handling-idempotency) |

Neither makes the node declare an effects class; both leave idempotency to the author. Ops AI's effects class (none,
read, model, write, human) driving retry and reconcile is stricter than either, and should stay an engine rule the SDK
cannot override upward (a pack may ask for fewer retries, never for a second send of a write).

## JSON Schema form renderers

| Library | Model | Conditions | Custom widgets | Fit for Ops AI |
|---|---|---|---|---|
| react-jsonschema-form (RJSF) | JSON Schema plus a `uiSchema` keyed by property: `ui:widget`, `ui:field`, `ui:order`, `ui:options`, `ui:definitions` | written in the JSON Schema itself (`dependencies`, `if`/`then`/`else`); the UI schema has no condition keys | a registry of named widgets and fields; `ui:field` replaces a whole subtree | Conditions in the data schema mean the server validator enforces them too. Its default theme markup is its own, so shadcn styling needs a full custom theme ([uiSchema reference](https://rjsf-team.github.io/react-jsonschema-form/docs/api-reference/uiSchema)) |
| JSON Forms (EclipseSource) | JSON Schema plus a separate UI schema of layouts (vertical, horizontal, group, categorization) and controls with a `scope` JSON pointer | `rule: { effect: HIDE \| SHOW \| ENABLE \| DISABLE, condition: { scope, schema } }`, where the condition is itself a JSON Schema tested against the data at `scope` ([rules](https://jsonforms.io/docs/uischema/rules)) | renderer registry of `{ tester, renderer }`; `rankWith(3, scopeEndsWith('rating'))` outranks the default of 2; a renderer gets `data`, `path` and `handleChange(path, value)` ([custom renderers](https://jsonforms.io/docs/tutorial/custom-renderers)) | Closest to the chosen model: layout and widgets outside the data schema, conditions written as JSON Schema that the server can evaluate with the same validator, and a ranked renderer registry that lets one node type replace one control or the whole form. The docs do not say whether hidden fields are validated, so Ops AI must decide that itself |
| uniforms (Vazco) | `AutoForm` over a schema "bridge": JSON Schema, SimpleSchema, Zod, custom | per field component logic | theme packages; custom fields via helpers | The bridge idea suits a codebase that already has Zod; it adds an abstraction Ops AI does not need when the registry already serves JSON Schema ([repo](https://github.com/vazco/uniforms)) |

Tradeoff between generated and custom forms, drawn from the platforms above:

| Approach | Gains | Costs | Seen at |
|---|---|---|---|
| Generated only, closed widget set | one renderer, consistent look, every field validated the same way, packs cannot run UI code | every new kind of input is a core change; complex nodes get long, flat forms | n8n (24 property types grew in core) |
| Hand-written per node | any interaction | every node looks different; validation lives in the browser; drift between dialog and runtime | Node-RED |
| Generated by default, ranked override per control or per node | common nodes cost nothing; rich nodes get a tailored editor | override code must be reviewed and must not become a second source of truth | JSON Forms renderer registry, RJSF `ui:field` |

## Comparison

| Platform | Node contract | Form definition | Dynamic options | Custom UI escape hatch | Credentials | Trigger model | Versioning | Distribution and trust |
|---|---|---|---|---|---|---|---|---|
| n8n | `INodeType`: description plus `execute`, `poll`, `trigger`, `webhook` or `supplyData`; declarative `routing` with no code | `properties` list with 24 property types, `displayOptions` show/hide, `typeOptions` | `methods.loadOptions`, `listSearch`, `resourceMapping`, run as node code with credentials at edit time; `loadOptionsDependsOn` | none for packages; new widgets are new core property types | `ICredentialType` with `authenticate`, `test`, `restrictToSupportedNodes`; decrypted in-process | poll (cursor in static data), webhook with register/remove hooks, long-lived trigger | light (`version` array plus `@version` conditions) or full (`VersionedNodeType`, `defaultVersion`); saved workflows keep their version | npm, installed at runtime from the UI; verified mode checks a vetted checksum; packages run in-process with full rights |
| Node-RED | runtime `.js` with `on('input', (msg, send, done))` plus editor `.html` | hand-written HTML dialog bound to `defaults` by element id | whatever the dialog's own script fetches | the whole dialog is custom (`oneditprepare`, `oneditsave`) | `credentials` text/password, stored apart from flows, passwords write-only in the editor | input nodes with no inputs that call `send` | none per instance; npm upgrade changes every flow (inference) | npm via the palette manager; Flow Library on manual submission; in-process |
| Windmill | a script's `main` function; return value is the result | JSON Schema inferred from the signature, adjusted in Generated UI | `DynSelect_<name>` type plus a function | none per script (inference); app builder is separate | typed resources (JSON Schema) holding `$var:` references to secrets | many trigger kinds feed a preprocessor that receives `event.kind` and raw fields | immutable content hash per deploy; old heads stay deployed | Hub and git sync; runs on workers |
| Pipedream | object with `props`, `methods`, `hooks`, `run` | `props`; shared `propDefinitions` per app | `options({ page, prevContext, query })`; `reloadProps` plus `additionalProps()` | none | app prop binds a managed account; `this.<app>.$auth` | sources `$emit` with `id`; platform dedupe `unique`, `greatest`, `last`; timer and HTTP interfaces injected | semver per component; bump every dependant on shared-file change | pull request to the public registry, automated checks, review |
| Zapier | `App` with `authentication`, `triggers`, `searches`, `creates`; `perform(z, bundle)` | `inputFields` | `dynamic` fields, functions returning fields, `altersDynamicFields` | none | `authentication` with `test`; `z.request` applies it | polling or REST hooks; dedupe on `id` or `primary` fields | immutable integration versions; `promote`, `migrate`, `deprecate` | Zapier-hosted; private until promoted |
| Ops AI today | `NodeType` dataclass plus an engine executor chosen by string | JSON Schema `parameters` only; console shows a JSON textarea | none; `agent` and `operation` are free strings | none | none on nodes; the tool gateway holds them | `ops.trigger.request` only | integer `version`, instance pins it | built into the engine package |

## Recommended Ops AI Node SDK contract

Build on the `NodeType` dataclass and the `NodeCall -> Outcome` executor that exist
(`packages/ops_engine/src/ops_engine/node_types.py`, `compiler.py:55-78`); the SDK is that shape made public,
plus the facts Forge and n8n showed the type must own.

### Type description fields

| Field | Meaning | Source of the idea |
|---|---|---|
| `id`, `version` | `<pack>.<group>.<name>`, integer; an instance pins both | Ops AI today; n8n saved-workflow pinning |
| `pack`, `nodes_api` | the pack id, pack version and content hash it came from; the engine contract level it was built against, refused at load when unsupported | n8n `n8nNodesApiVersion` (`nodes-api-version.ts`); Windmill hashes |
| `group`, `label`, `description`, `icon`, `docs_url` | palette and help text; the console has no other copy | Forge drift ([Forge study](forge-workflow-study.md#how-a-node-type-is-defined-and-added)) |
| `inputs`, `outputs`, `outputs_from` | ports with connection types; ports derived from a parameter | Ops AI today |
| `output_schema` per out port | JSON Schema of what the port carries; feeds the "earlier step outputs" picker and downstream validation | gap in Forge and in Ops AI today |
| `parameters` | JSON Schema 2020-12; the only data contract for settings, with show/hide conditions written as `if`/`then` inside it | RJSF conditions in the schema |
| `ui` | UI schema: field order and groups, widget per field, help and placeholder, `rules` (show, hide, enable, disable) whose conditions are JSON Schema over other parameters, option source per field, whether a field accepts a mapping | JSON Forms UI schema and rules |
| `effects` | none, read, model, write, human; decides retry and reconcile | Ops AI `RETRY_BY_EFFECTS` |
| `retry`, `timeout_seconds` | a pack may lower attempts; the engine refuses more than one attempt for `write` and `human` | Temporal and Inngest leave this to authors; Ops AI keeps it an engine rule |
| `requires` | the ports the executor may use (tools, models, agents, files, knowledge, timers, runs) and, for tools, the operation ids or patterns it may call | n8n `restrictToSupportedNodes`, inverted onto ports |
| `summary` | a template over parameters and output that gives the one-line text for the canvas card, the run view and the audit log | Pipedream `$.summary`; Forge's two `summarize` copies |
| `sensitive_outputs` | output paths always redacted in the journal view and audit export | n8n `sensitiveOutputFields` (`interfaces.ts:3190-3197`) |
| `deprecated`, `replaced_by` | hide from the palette; refuse new instances; existing runs continue | n8n `hidden`, `deprecated` (`interfaces.ts:2873-2890`) |
| `examples` | parameter fixtures and expected outcomes, used by the test harness and shown as help | Forge palette examples |

### Executor and context

`async def execute(call: NodeCall) -> Outcome`. The engine validates parameters against `parameters`, resolves
mappings, and hands the executor:

| `NodeCall` member | Contents |
|---|---|
| `params` | validated, mapped values |
| `key`, `iteration`, `attempt`, `run_id` | the stable key the executor passes to every external call (Temporal's run-plus-activity key, which Ops AI already builds as run:node:iteration:attempt) |
| `ports` | a scoped view of `EnginePorts` holding only what `requires` declares; an undeclared port raises |
| `log`, `progress` | journal-bound logging; no direct stdout |

`Outcome(port, out, summary)` names the out port. Two kinds of failure stay distinct, as they are in `ports.py`
today: a returned error port (the operation answered with an error) and a raised exception (no answer; the wrapper
retries if the effects class allows). Packs never import engine internals, the database, or an HTTP client; the review
lint and the worker's egress policy (deny all except the gateway, model and files endpoints) enforce the ports-only
rule. Inference: the import lint alone is not enough in Python, because a package can open sockets through any
dependency, so the network policy is the control that holds.

### Expression and mapping fields

Today a string that starts with `$.` is a path (`compiler.py:80-101`), and the resolver only walks dicts and lists; it
evaluates no code. Keep that: n8n's JavaScript expressions are what CVE-2025-68613 exploited. Change the stored shape
to a typed value, as Node-RED's TypedInput stores a value and its kind: `{"path": "$.nodes.parse.out.pages"}` for a
mapping, a bare value for a literal, and later `{"template": "Dear {{$.input.name}}"}` for interpolation without code.
That removes the case where a literal that starts with `$.` cannot be written, and lets the form show a step-output
picker for mapped fields without parsing strings.

### Option sources

Option sources are a closed, engine-owned set in the first version: `agents`, `tools` (filtered by access class and
`requires`), `knowledge`, `workflows`, `reviewerGroups`, `models`, `steps` (earlier nodes and their `output_schema`
paths). The console fetches them from one endpoint scoped to the caller's team. The validator checks on save and on
publish that each referenced id exists and the author can see it. Pack-defined option functions (n8n `loadOptions`)
run pack code with credentials at edit time; leave them out until a pack needs one, and then run them through the
same scoped ports as an executor with `read` effects.

### Form model

1. Generated by default. One console renderer (`SchemaForm`) reads `parameters` plus `ui` and builds the form from the
   app's shadcn primitives: text, textarea, number, select, switch, list, key-value mapping, step-output picker,
   option-source picker, JSON for `object` fields with no `ui`. Show/hide rules are JSON Schema conditions, so the
   browser (ajv) and the server (`jsonschema`, already used at `definition.py:210`) evaluate the same rule with a
   standard validator; no condition language is ported twice.
2. Custom form per type, optional. A custom form is a console component registered under the type id and a version
   range, either for one control (a ranked widget, as in the JSON Forms renderer registry) or for the whole form.
   Packs ship data only (`parameters`, `ui`); custom components live in the console build and are reviewed with it.
   Rules for a custom form:
   - it reads and writes the same parameter object the generated form would; it holds no state that is saved elsewhere;
   - the save path is the same: the server validates the submitted parameters against `parameters` whatever form
     produced them, and the custom form shows the server's errors by JSON pointer;
   - it uses the shared option-source endpoint, never its own fetches to other services;
   - a contract test renders it with each `examples` fixture and asserts the round trip leaves the parameters unchanged;
   - the generated form remains reachable for the same node (an "all settings" view), so support and review can see
     every value.
3. Hidden fields. A field hidden by a rule is dropped on save by a shared function, and a field required only when
   shown is expressed as `if`/`then` in `parameters`, so the server enforces it (n8n does this in shared code with
   `getNodeParameters`, `node-helpers.ts:773`).

### One description, three readers

| Reader | Reads | From |
|---|---|---|
| Editor | palette, ports, form, help, summary, option sources | `GET` node types: `registry.get(id, version).view()` |
| Validator | `parameters` (including conditions), `ui` option sources for reference checks, port names for connections | the same `NodeType` |
| Runner | `parameters`, `effects`, `retry`, `requires`, `executor`, `output_schema` (checks what the executor returned) | the same `NodeType` |

A registry conformance test enforces it: for every registered type, every `ui` field names a real parameter, every
option source is known, every rule condition is valid JSON Schema, every `examples` fixture validates and runs against
fake ports, every output validates against its port's `output_schema`, and a `write` type called twice with the same
key sends once.

### Test harness

The SDK ships `ops_engine.testing`: fake ports (tools, agents, files, reviews) that record calls and keys, a
`run_node(type, params, input)` helper that goes through the real wrapper (journal, retry, reconcile), a crash
injector that kills the step after the port call and before the journal write, and the conformance test above as a
function a pack runs in its own CI. No real model calls: the agent port fake returns fixtures.

### Packs and trust

| Rule | Reason |
|---|---|
| Packs are Python packages with a manifest (id, version, `nodes_api`, types, `requires` per type), installed at deploy time from an internal index with pinned hashes (`pip --require-hashes`) | n8n's runtime install from npm is how the January 2026 OAuth theft reached instances |
| The registry loads only packs on the deployment's allowlist, and records pack id, version and hash on every journal row | audit can name the exact code that ran a step; Windmill's hash pinning |
| A new pack version never changes a saved workflow; an author moves a node to a new type version with an explicit, recorded migrate step, with an optional `migrate(params)` the pack supplies | Zapier `promote` and `migrate`; n8n "upgrading could cause all workflows using the node to break" |
| Review checks: no network, filesystem or environment access outside ports; no runtime dependencies beyond an allowlist; conformance test passes | n8n verification rules ("no access to environment variables or file system") |
| Credentials never reach a node: the tool gateway holds them and binds each operation to the packs and types allowed to call it; any secret a form shows is write-only with a `has_<name>` flag | n8n `restrictToSupportedNodes`; Node-RED password credentials |

## Trigger adapter contract

Triggers run outside the graph as adapters and call one start API. The `ops.trigger.*` node in the graph declares the
input schema and the adapter's configuration (mailbox, cron, path, poll operation); it does no work at run time beyond
emitting the payload, as `ops.trigger.request` does today.

Adapter interface: `verify(raw, headers, config) -> Verified`, `normalise(raw, headers) -> payload`,
`dedupe_key(event) -> str`. The adapter sends the start API one envelope:

| Field | Meaning |
|---|---|
| `workflow`, `version` | the published workflow and, when pinned, its version |
| `trigger` | adapter kind and the trigger node id |
| `received_at` | adapter clock |
| `raw` | a Files reference to the exact bytes received (for audit and re-verification) |
| `headers` | the transport headers kept for audit, secrets stripped |
| `payload` | normalised input, validated against the trigger node's `inputSchema` |
| `dedupe_key` | unique per real-world event; the start API returns the existing run for a key it has seen within the window (Inngest: 24 hours) |
| `verified` | how the event was authenticated: method, key id, result |

| Adapter | Dedupe key | Verification |
|---|---|---|
| Email | mailbox plus `Message-ID` | record SPF, DKIM and DMARC results; attachments to Files before the run starts |
| Schedule | workflow plus scheduled tick time (the planned time, so a retried tick is the same key) | internal; a missed-tick policy (skip or catch up) on the trigger node |
| Webhook | provider event id header when present, else SHA-256 of the raw body | HMAC over the raw bytes (Windmill keeps `raw_string` for this), constant-time compare, timestamp tolerance to refuse replays; reject before any run exists |
| Poll | item id from the poll operation; the engine owns the cursor per trigger instance with Pipedream's strategies (`unique`, `greatest`, `last`) | the poll call goes through the tool gateway as a `read`, under the gateway's credentials |
| Request (API) | caller-supplied `Idempotency-Key` header | the API's own authentication |

n8n leaves cursors and dedupe to each polling node's static data; putting both in the adapter layer means every
trigger gets the same guarantee and the audit log shows why a duplicate did not start a run.

## Pitfalls to avoid

| Pitfall | Platform that hit it | Ops AI guard |
|---|---|---|
| Per-type facts spread over five files and drifting | Forge ([Forge study](forge-workflow-study.md#how-a-node-type-is-defined-and-added)) | one `NodeType`, three readers, conformance test |
| Packages installed at runtime, running in-process with full rights, stealing credentials | n8n (community node risks; January 2026 npm campaign) | deploy-time allowlisted packs, ports-only, egress policy, credentials in the gateway |
| Code-evaluating expressions leading to RCE | n8n (CVE-2025-68613, CVSS 9.9) | path-only mappings and code-free templates |
| Validation only in the editor | Node-RED (`defaults.validate` is described as an editor check) | server validates every save and publish against `parameters` |
| Hand-written dialogs per node | Node-RED | generated form by default; custom forms reviewed in the console build |
| Every new widget a core change, forms grow into sub-editors | n8n (24 property types, `resourceMapper`, `filter`, `assignmentCollection`) | ranked widget registry, so a richer control is a console addition and the property types stay JSON Schema |
| Edit-time option loaders running node code with credentials | n8n `loadOptions` | closed option-source set served by the platform |
| Unversioned upgrades breaking saved workflows | n8n authors who skip versioning; Node-RED flows with no version field | pinned type versions, explicit migrate |
| Dedupe and cursors re-implemented per node | n8n poll nodes | dedupe key and cursor in the adapter layer and start API |
| Mapping strings that cannot express some literals | n8n `=` prefix; Ops AI `$.` prefix today | typed `{path}` values |

## What to build first

Slices of at most eight tasks; each ends with a use case run through the console and the API.

| Slice | Tasks |
|---|---|
| 1. Generated form | add `ui` and `output_schema` to `NodeType` and `view()`; write `ui` for the seven built types; registry conformance test; console `SchemaForm` from shadcn controls replacing the textarea at `node-inspector.tsx:106-117`; option-source endpoint for agents, tools and steps; server errors shown by JSON pointer; typed `{path}` mapping with a one-off migration of saved definitions; use case: build and run a workflow through the form only |
| 2. Node SDK and packs | scoped `NodeCall.ports` from `requires`; `summary` and `sensitive_outputs` in the journal view; `ops_engine.testing` (fake ports, `run_node`, crash injector); pack manifest and loader with allowlist and hash; move the seven types into an `ops.core` pack; journal rows carry pack id, version and hash; one sample pack built from the harness; use case: a write node crashed after send reconciles and sends once |
| 3. Custom forms | console custom-form registry (per control, per type, version range); round-trip contract test; human review options editor as the first custom form; "all settings" generated view for any node; use case: author options through the custom form and approve a run |
| 4. Trigger adapters | start API with `dedupe_key` and a window; webhook adapter with HMAC over raw bytes; schedule adapter with tick keys; email adapter with Message-ID; poll adapter with engine-owned cursors; adapter audit envelope stored with the run; use case: the same webhook delivered twice starts one run |

