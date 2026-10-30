# Building a plugin

Status: current on main behind the `OPS_PLUGINS` switch, which is off until the plugins release; what is not built
yet is listed at the end. Design: the planning repo `docs/plans/ops-ai/plugin-architecture.html`.

A plugin brings one outside system to Ops AI as a single installable package: how a team signs in to it, the tools
agents may call on it, the knowledge it can feed into a knowledge base, and agent templates that use those tools. It is
a Python package holding a `plugin.yaml` manifest. Most plugins are only that file: tools-service runs each tool from
its request template, so no plugin code runs for them. A tool's paging, and a query built from a model's values, are
data too. Python is used only where the manifest cannot say what a tool does, such as making several requests or
reading a binary answer. The worked example is
Salesforce, in the built-in plugins repository at `plugins/salesforce/`; every path below is relative to that folder
unless it says otherwise. The repository is private at <https://github.com/chanl-ai/ops-ai-plugins>, cloned beside
ops-ai. Changes to it go on a branch and through a pull request.

## What a plugin holds

| Part | Where | What it does |
|---|---|---|
| Manifest | `src/ops_plugin_salesforce/plugin.yaml` | Id, version, connection, settings, tools, knowledge sources and templates, schema `ops-ai/plugin@2` |
| Entry point | `pyproject.toml`, group `ops_ai.plugins` | How tools-service finds the installed plugin: `salesforce = "ops_plugin_salesforce:plugin"` |
| Plugin object | `src/ops_plugin_salesforce/__init__.py` | `plugin = Plugin.beside(__file__)`, which reads the manifest next to it |
| Python tools | `src/ops_plugin_salesforce/kb.py` | Functions marked `@tool(access=...)`, named from the manifest by `function: module:name` |
| Templates | `src/ops_plugin_salesforce/templates/` | Agent definitions the manifest lists under `templates`; validated only, not installable yet |
| Tests | `tests/test_tools.py` | Each tool against a fake of the system, through the SDK's runner |

## The manifest

| Field | What it says |
|---|---|
| `id`, `title`, `version`, `sdk` | `id` is reverse-domain (`opsai.salesforce`); the part after the last dot prefixes every tool name (`salesforce_query`) |
| `connection.kinds` | Sign-in kinds the system accepts: `oauth2_auth_code`, `oauth2_client_credentials`, `oauth2_jwt_bearer`, `api_key`, `basic`, `bearer` or `none` |
| `connection.authorize_url`, `token_url`, `revoke_url`, `scopes` | The OAuth app's addresses and scopes; `{setting}` placeholders are filled from settings |
| `connection.sign_in` | Who signs in: `team`, `person` or `person_or_team`; `person` needs a kind that holds each person's token (`oauth2_auth_code`), and validate refuses it otherwise |
| `connection.api_key` | For `api_key`: `{placement: header \| query, name}`, how the system takes its key; validate refuses an `api_key` plugin without it |
| `connection.from_token`, `token_hosts` | Settings read from the token answer (Salesforce's `instance_url`), and the host suffixes such a value must end in |
| `connection.health_check` | The path Test connection calls |
| `settings` | Values a team sets. `default`, `lockable` (the platform admin can fix it for every team) and `from_token` (only the sign-in sets it) |
| `egress` | The hosts a tool may reach, usually a setting such as `{instance_url}` |
| `endpoint` | The base address every request template is relative to |
| `tools` | Each tool's `name`, `title`, `description`, `access` (`read` or `write`), `input`, then either `request` (method, path, `query`, body, `paging`) and an optional Jinja `transform`, or `function` |
| `knowledge_sources` | A source's `list` and `get` tools and its `schedule` |
| `templates` | Each template's kind, id, file, and the tools and bindings it needs |

A write tool waits for a person's approval before it runs unless its manifest entry sets `requires_approval: false`.
A tool's `title` (at most 60 characters, such as "Find cases") is what the tools picker, the agent page and the
approval cards show in place of its operation name.

## Paging and queries

A listing tool says how it reaches its next page in `request.paging`, with one of three rules:

| Rule | Fields | Example |
|---|---|---|
| `link` | `next`: the answer field holding the next page's address | Salesforce's `nextRecordsUrl`, Graph's `@odata.nextLink` |
| `token` | `next`: the answer field holding a token; `param`: the parameter it is sent back as | Salesforce UI API's `nextPageToken`, sent as `pageToken` |
| `offset` | `items`: the answer's list; `limit`: the page size; `offset_param` and `limit_param` when not `offset` and `limit` | Salesforce's `parameterizedSearch`, with `limit_param: overallLimit` |

An agent's call gets one page and a `next_cursor`, and asks again with the cursor alone for the next. tools-service
seals the cursor to the tenant, the connection and the tool, so a caller cannot change it or use it on another tool. A
page address is followed only as a GET to one of the plugin's hosts, carrying the connection's sign-in and nothing of
the first call. A knowledge sync reads every page, up to 200 a run, and starts the listing again from its watermark
when the system has forgotten a saved page.

A query is built from the tool's inputs in `request.query`, a map of parameter names to templates: `{{name}}` is the
input's value, checked and written in by its format. An input a query template uses must declare an `enum` or a
`format`; `ops plugin validate` refuses one with neither, and one with only a `pattern`, which is for path segments.

| Format | Checked | Written as |
|---|---|---|
| `soql_string` | Text | Escaped so it cannot leave its quotes; the template writes the quotes (`'{{subject}}'`), and validate refuses one without them |
| `sosl_term` | Text | SOSL's reserved characters escaped, so a term cannot close `FIND {...}` and add a clause |
| `salesforce_id` | 15 or 18 letters and digits | As given |
| `date-time` | A date and time, any offset | UTC, `2026-10-01T09:00:00Z` |
| `date` | A date | `2026-10-01` |

An enum's values are written as the manifest gives them, and may hold only letters, digits, space, `_`, `-` and `.`.
An array input renders its checked items joined by commas. Inputs nest as `type: object` with `properties` and
`type: array` with `items`, up to three levels and fifty items. An input with a `default` fills its place when a call
leaves it out. An input a query uses is not also sent as its own parameter. `find_cases` in the Salesforce manifest
is the worked example:

```yaml
- name: find_cases
  title: Find cases
  access: read
  input:
    status: { type: string, enum: [New, Working, Escalated, Closed] }
    since: { type: string, format: date-time, required: false, default: "1970-01-01T00:00:00Z" }
  request:
    method: GET
    path: /query
    query:
      q: >-
        SELECT Id, CaseNumber, Subject, Status FROM Case
        WHERE Status = '{{status}}' AND LastModifiedDate > {{since}} ORDER BY LastModifiedDate, Id
    paging: { rule: link, next: nextRecordsUrl }
```

## Writing a Python tool

A function receives a `Context` and its inputs as keyword arguments, and returns what the tool answers. Every
parameter after `ctx` is declared under the tool's `input`, since tools-service checks each call against the declared
inputs and refuses anything else; `ops plugin validate` reports a parameter left out. A listing tool declares `since`
and `cursor` with `required: false`, because its first page has neither.

| `ctx` member | Use |
|---|---|
| `ctx.settings.<name>` | The team's settings, with defaults and locked values applied |
| `ctx.http.get/post/patch/request` | The only way out. It adds the connection's sign-in, and refuses a host the manifest's `egress` does not list or the workspace's allow-list does not hold (`EgressDenied`) |

Raise `BadInput` for an input the tool refuses, `NeedsReconnect` when the system rejects the sign-in, and
`RateLimited` when it asks to slow down. A list tool's `next_cursor` is sealed by tools-service before it leaves, so a
model or a caller cannot change it between pages.

## Knowledge sources

A knowledge source names two read tools. The `list` tool takes `since` and `cursor` and answers
`{items: [{id, title, updated_at}], next_cursor?, watermark?}`. The `get` tool takes `id` and answers
`{id, title, updated_at, mime, encoding, content, url, children?}`; `children` are attachments, synced and removed with
their parent. kb-service calls both through tools-service, so the system's token never leaves tools-service. It
fetches only items whose `updated_at` moved, saves its place after every page, resumes after a rate limit, and pauses
the source when the connection needs signing in again. A source can only use a connection the team signs in to as a
team, since a scheduled sync has no person behind it.

## Check and test a plugin

Clone the plugins repository beside ops-ai once, then run both from the ops-ai checkout:

```
git clone https://github.com/chanl-ai/ops-ai-plugins.git ../ops-ai-plugins
uv run ops plugin validate ../ops-ai-plugins/plugins/salesforce
uv run ops plugin test ../ops-ai-plugins/plugins/salesforce
```

`validate` prints `OK <id> <version>: N tools, N knowledge sources, N templates`, or each problem with its field. It
refuses, among others, an unknown sign-in kind, a write used as a knowledge tool, a template that needs a tool the
plugin lacks, and a Python tool whose `access` disagrees with its manifest entry. `test` runs the plugin's own pytest
suite with the plugin's `src/` on the path, so a plugin in its own repository needs no install to be tested. A test calls a tool as tools-service would with `ops_plugin_sdk.testing.call(plugin, tool, args, settings,
Fake(client, token))`, where `client` is an `httpx.Client` bound to a fake of the system.

## Install a plugin

| How | When |
|---|---|
| A built-in from `ops-ai-plugins`, pinned per release | A plugin shipped with an install |
| Add it to the environment tools-service runs in (`uv add`) | A plugin a customer brings |
| List its folder in `OPS_PLUGIN_PATHS` (a JSON list) | A plugin under development, without packaging |

tools-service loads every plugin when it starts. A plugin that fails validation is listed under `failed` at
`GET /v1/plugins` with its error, and every other plugin still loads.

## Turn a plugin on

Plugins run only where `OPS_PLUGINS=true` is set for tools-service and kb-service. Off, nothing is loaded, the plugin
routes answer 404 and kb-service refuses a plugin source (`tools_unavailable`). With it on, a plugin is still off until two people turn it on.
There is no Plugins page yet; both switches are API calls.

| Who | Call | What it does |
|---|---|---|
| Platform admin (`settings.manage`) | platform-service `PUT /v1/policies/plugins` with `{value: {"opsai.salesforce": {enabled: true, locked: {api_version: "61.0"}}}}` | Allows it for the install and fixes any lockable setting; off again stops every team's calls within seconds |
| Account admin (`settings.manage`) | the policy entry's `client: {id}`, then tools-service `PUT /v1/plugins/opsai.salesforce/app-secret` with `{clientSecret}` | Sets up the platform's own OAuth app once for every team; the secret is sealed at the account and no read returns it |
| Team admin (`connections.manage`) | tools-service `PUT /v1/plugins/opsai.salesforce/team` with `{enabled, settings, signIn, kind, credentials, clientId, clientSecret}` | Turns it on for the team and makes the team's connection, whole, for its sign-in kind (below); off again keeps the connection and settings |
| Security | tools-service `POST /v1/egress/hosts` | Adds the system's hosts to the workspace's allow-list, as for any outside system |
| Team admin | `POST /v1/connections/{id}/sign-in`, then `/sign-in/complete` | Signs the team in; `from_token` settings are read from the token answer here |

The first turn-on makes the connection in one call, whatever the plugin's kind. `kind` picks one of the plugin's
`connection.kinds` (the first when left out) and cannot change once the connection exists (`kind_fixed`).
`credentials` holds the kind's own fields: a key is sealed and never answered back, and a later turn-on that sends one
part replaces only that part. Test connection reads the manifest's `health_check` for every kind.

| Kind | `credentials` | What tools-service adds to each call |
|---|---|---|
| `none` | nothing | nothing |
| `api_key` | `key` | the key in the header or query parameter `connection.api_key` names |
| `basic` | `username`, `password` | `Authorization: Basic` |
| `bearer` | `token` | `Authorization: Bearer` |
| `oauth2_client_credentials` | none; `clientId` and `clientSecret` beside it, or the platform's app | a token from `token_url`, fetched and renewed by tools-service |
| `oauth2_auth_code` | none; the OAuth app as above | the team's or each person's token after they sign in |
| either OAuth kind, app proves itself with its certificate | `clientAuth: private_key_jwt`, `signingCertificate`, `signingKey`; `clientId` beside it, no client secret | a token asked for with a client assertion signed by the key (RFC 7523), on every token request, refresh, sign-in and disconnect; Microsoft Entra apps at banks |
| `oauth2_jwt_bearer` (signed service account) | `signingKey`, optionally `signingCertificate`, `subject`, `audience`, `scopeIn` (`form` or `claim`); `clientId` is the issuer | a token whose grant is a JWT signed by the key, signed again when it expires; DocuSign (client id = integration key, `subject` = user id, `audience` = `account-d.docusign.com`) and Google (client id = service account email, `scopeIn: claim`) |
| any kind | `clientCertificate`, `clientKey`, `trustedCa` | the client certificate on the TLS handshake; a refused handshake fails `TLS_FAILED` |

A wrong key, password or token fails Test connection naming the system's 401 and a call with `UPSTREAM_ERROR` 401; a
wrong client secret fails the token fetch with `AUTH_FAILED` and marks the connection `needs_reconnect`. A Python tool's
answer is scrubbed of the connection's credential, as a data tool's is.

The signing key and certificate are their own pair, apart from the mTLS `clientCertificate` and `clientKey`, so the
signing key is never offered on a TLS handshake. Saving a key that does not belong to its certificate is refused naming
both, also when only one half changes. Every read shows the certificate's SHA-256 thumbprint, subject, expiry and
whether it expires within 30 days, never the key. A certificate past its expiry is refused before any token request,
as `AUTH_FAILED` "the signing certificate expired on <date>", and marks a team connection `needs_reconnect`. The
system's own refusal of an assertion (another key, a replay) is `AUTH_FAILED` naming its host and error, and is never
retried with a secret. RS256 (RSA keys) and ES256 (P-256 keys) are the algorithms; any other key is refused.

A team that gives `clientId` and `clientSecret` signs in with its own OAuth app; one that gives neither uses the
platform's. `signIn` is `team` (one team account), `person` (each person connects their own account, from the chat card
or Your connections, and calls act as them) or `person_or_team` (each person, with the team account as backup). A plugin
lists which of these it allows. One team's app, connection or token never serves another team, and one person's token
never serves anyone else.

After that, builders grant the plugin's tools to agents as any other tool, and a knowledge base adds a source with
`POST /v1/sources` and `{type: "tool", config: {plugin: "opsai.salesforce", source: "articles"}}`. Nobody can edit,
publish or delete the plugin's tool module; a new plugin version replaces it.

## Proof

Use cases uc-564 and uc-581 run all of this against a fake Salesforce on main: `make usecase-test UC=uc-564` and
`make usecase-test UC=uc-581`, then `make usecase-report UC=<id>` for their stories. uc-581 runs the seven query tools,
paging, the checks on query values, the sync's restart and the tools picker's titles. uc-588
(`make usecase-test UC=uc-588`) turns on one test plugin per sign-in kind from `services/tools-service/tests/plugin_kinds`
against `docs/usecases/lib/fake_multi_auth.py`, a person's own sign-in from chat, and a client certificate;
`docs/usecases/tools-service/scripts/evidence-uc-588-stripe.py` runs the bearer kind against Stripe in test mode.
uc-583 (`make usecase-test UC=uc-583`) turns on Entra, Google and DocuSign style plugins from
`services/tools-service/tests/plugin_signed` against `docs/usecases/lib/fake_token_endpoint.py`, which checks each
assertion as Entra does.

## Not built yet

| Gap | Today |
|---|---|
| Plugins page in the console | API switches only |
| Installing a template as a team's own agent | Templates are validated, not installed |
| Per-person access lists | Stored on the binding, not enforced |
| Adding a plugin knowledge source from the console | kb-service API only; the source page syncs and shows it |
| Plugins running out of process | Python tools run inside tools-service |
| Inbound webhooks a plugin declares | Designed in an earlier change's spec; built in an earlier change |
| Headers, form bodies, extra sign-in parameters, a lookup after sign-in and amount limits in the manifest | Planned as their own card, after paging |
| One rate window per connection, Retry-After, and recorded fakes with standard cases | Planned |
| A signed client assertion and the JWT grant, and knowledge items over 25 MB | Planned; a client certificate on the TLS handshake works today |
| Each person giving their own key, password or token | Planned; each person signs in only with `oauth2_auth_code` today |
