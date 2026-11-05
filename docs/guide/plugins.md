# Building a plugin

Status: current. Plugins load from the install's plugins folder, with no switch. What is not built yet is listed at
the end.

A plugin brings one outside system to Ops AI as a single installable package: how a team signs in to it, the tools
agents may call on it, the knowledge it can feed into a knowledge base, and agent templates that use those tools. It is
a Python package holding a manifest file. Most plugins are only that file: the tools service runs each tool from
its request template, so no plugin code runs for them. A tool's paging, and a query built from a model's values, are
data too. Python is used only where the manifest cannot say what a tool does, such as making several requests or
reading a binary answer. The worked example is Salesforce in the built-in plugins repository; every path below is
relative to that folder unless it says otherwise. Changes to that repository go on a branch and through a pull request.

The manifest file is `plugin.yaml`. The Salesforce example lives at `plugins/salesforce/`.

## What a plugin holds

| Part | Where | What it does |
|---|---|---|
| Manifest | `src/ops_plugin_salesforce/plugin.yaml` | Id, version, connection, settings, tools, knowledge sources and templates, schema `ops-ai/plugin@2` |
| Entry point | `pyproject.toml`, group `ops_ai.plugins` | How tools-service finds the installed plugin: `salesforce = "ops_plugin_salesforce:plugin"` |
| Plugin object | `src/ops_plugin_salesforce/__init__.py` | `plugin = Plugin.beside(__file__)`, which reads the manifest next to it |
| Python tools | a module beside the manifest | Functions marked `@tool(access=...)`, named from the manifest by their full import path, `function: <package>.<module>:<function>`. Salesforce has none; `services/tools-service/tests/plugin_desk/kb.py` in ops-ai is a small one |
| Templates | `src/ops_plugin_salesforce/templates/` | Agents, skills, workflows and document types the manifest lists under `templates`; a team adds its own copy from the App's Resources tab |
| Tests | `tests/test_tools.py` | Each tool against a fake of the system, through the SDK's runner |

## Start a new plugin

The smallest plugin is four files: a package file, a manifest, the line that loads the manifest, and one test. This one
signs in with an API key and has one read tool. Make the folder anywhere, then check and test it from the ops-ai
checkout, as below.

```
ticketdesk/
  pyproject.toml
  src/ops_plugin_ticketdesk/__init__.py
  src/ops_plugin_ticketdesk/plugin.yaml
  tests/test_tools.py
```

`pyproject.toml` names the package and the entry point tools-service finds it by:

```toml
[project]
name = "ops-plugin-ticketdesk"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["ops-plugin-sdk"]

[project.entry-points."ops_ai.plugins"]
ticketdesk = "ops_plugin_ticketdesk:plugin"

[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ops_plugin_ticketdesk"]
```

`src/ops_plugin_ticketdesk/__init__.py` loads the manifest beside it:

```python
from ops_plugin_sdk import Plugin

plugin = Plugin.beside(__file__)
```

`src/ops_plugin_ticketdesk/plugin.yaml` is the plugin itself (every field is in The manifest, below):

```yaml
schema: ops-ai/plugin@2
id: acme.ticketdesk
title: Ticket desk
version: 0.1.0
sdk: "1"

connection:
  kinds: [api_key]
  api_key: { placement: header, name: X-Api-Key }
  sign_in: [team]
  health_check: { path: /me }

settings:
  api_url: { type: string, default: "https://api.ticketdesk.example", title: API address }

egress: ["{api_url}"]
endpoint: "{api_url}"

tools:
  - name: get_ticket
    title: Get a ticket
    description: One ticket by its number, with its subject and status
    access: read
    input:
      number: { type: integer, description: "The ticket number, such as 4182" }
    request:
      method: GET
      path: "/tickets/{number}"
```

`tests/test_tools.py` calls the tool against a fake of the system, as tools-service would:

```python
import httpx
from ops_plugin_ticketdesk import plugin

from ops_plugin_sdk.testing import Fake, call

SETTINGS = {"api_url": "https://api.ticketdesk.test"}


def test_get_ticket_sends_the_number_in_its_path() -> None:
    seen: list[httpx.Request] = []

    def desk(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"number": 4182, "subject": "Printer jam", "status": "open"})

    client = Fake(httpx.Client(transport=httpx.MockTransport(desk)), "k-1")
    out = call(plugin, "get_ticket", {"number": 4182}, SETTINGS, client)
    assert seen[-1].url.path == "/tickets/4182"
    assert out["status"] == "open"
```

Then, from the ops-ai checkout:

```
uv run ops plugin validate ../ticketdesk
uv run ops plugin test ../ticketdesk
```

`validate` prints `OK acme.ticketdesk 0.1.0: 1 tools, 0 knowledge sources, 0 templates` and `test` prints `1 passed`.
The test runner sends the key as a bearer token whatever `connection.api_key` names, so assert the key's header on a
local stack (Try a plugin on a local stack), not in the test. To see it in the console, install it (Install a plugin)
and connect it from Apps. Salesforce and GitHub in the plugins repository are the fuller examples: OAuth sign-in,
paging, knowledge sources and templates.

## The manifest

| Field | What it says |
|---|---|
| `id`, `title`, `version`, `sdk` | `id` is reverse-domain (`opsai.salesforce`); the part after the last dot prefixes every tool name (`salesforce_query`) |
| `connection.kinds` | Sign-in kinds the system accepts: `oauth2_auth_code`, `oauth2_client_credentials`, `oauth2_jwt_bearer`, `api_key`, `basic`, `bearer` or `none` |
| `connection.authorize_url`, `token_url`, `revoke_url`, `scopes` | The OAuth app's addresses and scopes; `{setting}` placeholders are filled from settings |
| `connection.sign_in` | Who signs in: `team`, `person` or `person_or_team`; `person` needs a kind that holds each person's own credential (`api_key`, `basic`, `bearer` or `oauth2_auth_code`), and validate refuses it on a plugin whose kinds are only `none`, `oauth2_client_credentials` or `oauth2_jwt_bearer` |
| `connection.api_key` | For `api_key`: `{placement: header \| query, name}`, how the system takes its key; validate refuses an `api_key` plugin without it |
| `connection.from_token`, `token_hosts` | Settings read from the token answer, and the host suffixes such a value must end in |
| `connection.after_sign_in` | One lookup after sign-in that fills a setting (Salesforce's instance from UserInfo); see Headers, forms and sign-in steps |
| `connection.client_auth`, `authorize_params` | How the OAuth client is sent on the token call, and extra parameters on the sign-in address |
| `connection.health_check` | The path Test connection calls |
| `connection.sign_in_errors` | What a refused sign-in says, by the system's error code: `{error, description_contains?, say, who}`; see Where a team signs in |
| `connection.credential_settings` | Settings that belong to the OAuth app's registration (a Microsoft tenant, an Okta domain): the team's app credential holds them, and every account signing in with it reads them from there |
| `settings` | Values a team sets. `default`, `lockable` (the install can fix it for every team, `OPS_PLUGIN_LOCKED`), `from_token` or `after_sign_in` (only the sign-in sets it), and `choices` and `other` (the only values it takes; see Where a team signs in) |
| `headers` | Headers on every request the plugin makes, a Python tool's too; a tool's own `headers` add to them |
| `egress` | The hosts a tool may reach, usually a setting such as `{instance_url}` |
| `endpoint` | The base address every request template is relative to |
| `tools` | Each tool's `name`, `title`, `description`, `access` (`read` or `write`), `input`, `headers`, `amount_max`, `requires_approval`, `rate_limit_per_min` (calls a minute, 60 when left out), `knowledge` (`list_items` or `get_item` for a knowledge source's tools), then either `request` (method, path, `query`, `body` or `form`, `paging`) and an optional Jinja `transform`, or `function` |
| `knowledge_sources` | A source's `list` and `get` tools and its `schedule` |
| `templates` | Each template's `kind` (`agent`, `skill`, `workflow` or `document_type`), `id`, `version`, `path` (its file, relative to the manifest), and `requires`: `tools` (names without the prefix; validate refuses one the plugin lacks) and `bind` (what a team fills in on its copy, such as `{model_alias: chat}` or `{knowledge_base: "Salesforce articles"}`) |
| `display` | What the console's App card shows: `logo` (a URL or a `data:` URI), `category`, `description` (one line) and `docs_url` (where an admin reads how to register the system's app or get its key) |

A write waits for a person's approval only when the team's approval policies say so (apps.md, Approvals) or its
manifest entry sets `requires_approval: true`; approvals are off by default. A tool's `title` (at most 60
characters, such as "Find cases") is what the tools picker, the agent page and the approval cards show in place of
its operation name.

### Request templates

| Part | How it is written | Example |
|---|---|---|
| `path` | `{input}` for a path segment, URL-encoded; give the input a `pattern` so a value cannot change the path | `"/repos/{owner}/{repo}/issues/{number}"` |
| `query` | A map of parameter names to text; `{{input}}` is checked and written by its `enum` or `format` (below), and text with no `{{...}}` is sent as written | `{state: "{{state}}", per_page: "50"}` |
| `body` | One string of JSON. Each `{{input}}` is written as JSON, quotes included, so it is never put inside quotes; validate refuses one in quotes, one naming no input, and a body that is not JSON once the inputs are written in | `'{"body": {{body}}}'` sends `{"body": "Seen again on \"Leeds\"."}`; `"{{fields}}"` sends a whole object input |
| `form` | A map for a form-encoded body (Headers, forms and sign-in steps) | Slack's `chat.postMessage` |


## Paging and queries

A listing tool says how it reaches its next page in `request.paging`, with one of five rules:

| Rule | Fields | Example |
|---|---|---|
| `link` | `next`: the answer field holding the next page's address | Salesforce's `nextRecordsUrl`, Graph's `@odata.nextLink` |
| `link_header` | none: the next page's address is the answer's `Link` header, `rel="next"` | GitHub, GitLab |
| `token` | `next`: the answer field holding a token; `param`: the parameter it is sent back as | Salesforce UI API's `nextPageToken`, sent as `pageToken` |
| `offset` | `items`: the answer's list; `limit`: the page size; `offset_param` and `limit_param` when not `offset` and `limit` | Salesforce's `parameterizedSearch`, with `limit_param: overallLimit` |
| `page` | `limit`: the page size; `param` (default `page`) and `limit_param` (default `limit`); `start`, the first page's number (default 1); `items` when the list is not the whole answer | An API that takes `page=2&per_page=50` |

With `offset` and `page`, a page shorter than `limit` is the last. A list answer that pages is returned as
`{records: [...], next_cursor}` while there is a next page, and as the list on the last one.

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

## Headers, forms and sign-in steps

Six fields cover what a system asks for beyond a path and a query. Each is data, checked by `ops plugin validate`
and run by tools-service.

| Field | What it does | Example | What validate refuses, and why |
|---|---|---|---|
| `headers` (plugin), `tools[].headers` | Sent on each request: the plugin's first, then the tool's, then the connection's sign-in, which wins over a name they share. Fixed text or `{setting}`; a header whose setting is unset is left out | Graph's `ConsistencyLevel: eventual`, `Sforce-Query-Options: batchSize={query_batch_size}` | `Authorization`, `Proxy-Authorization`, `Cookie`, `Host` or the API key's name in any case, `{{`, or a secret setting: a header never carries a credential. Headers on a Python tool: it takes the plugin's |
| `request.form` | A form-encoded body in place of `body`; each field fixed text or `{{input}}`, a field whose input is not given left out | Slack's `chat.postMessage`, Stripe's creates | A form with `body`, a form on GET or DELETE, a field naming no input |
| `connection.authorize_params` | Added to the sign-in address; fixed text or `{setting}` | Atlassian's `audience: api.atlassian.com`, `prompt: consent` | A name the platform sets (`state`, `client_id`, `redirect_uri`, `code_challenge`, `scope`, `response_type`, `login_hint`, `resource`): tools-service drops those on every connection anyway |
| `connection.client_auth` | How the OAuth client is sent on the token call: `body`, `basic` or `private_key_jwt` | Zoom takes only `basic` | On a plugin with no OAuth kind |
| `connection.after_sign_in` | One GET with the token just issued, whose value at `read` fills `setting`. `url` is https, or a path on the sign-in host (the origin of `token_url`) | Salesforce: `{url: /services/oauth2/userinfo, read: urls.custom_domain, setting: instance_url}`; Atlassian: `read: "[0].id"` of accessible-resources | A host outside `egress`, a setting not marked `after_sign_in`, an unreadable path, no `token_hosts` |
| `tools[].amount_max` | The most the tool's `amount` input may be; a call over it, or without an amount, is refused before it leaves | A core-banking transfer | No number input named `amount`, or a paged tool |

Every request template also refuses a secret reference (`{{NAME}}` in capitals): tools-service resolves those from the
calling team's secrets, so one in a plugin would send the team's secret to the plugin's host. A team setting that a
header renders and that holds `{{` or a line break turns the plugin's calls off for that team, naming the setting.

The lookup follows no redirect, and fails the sign-in, storing no token, when it answers anything but 200, names no
value, names an address outside `token_hosts`, or names a plain value with anything but letters, digits, `.`, `_`, `-`
and `:`. The team admin's own sign-in sets or replaces the value; a person's own sign-in sets it only when none is held,
and one that reaches a different site is refused as "signed in to another site", so one person cannot point the team's
calls at another tenant. That rule is `settle_at_sign_in` in tools-service's `plugins/host.py`, the one place it lives.

## Where a team signs in, and what a refused sign-in says

A setting with `choices` takes only one of them, or, with `other`, a host the person types: `other.value` is the
setting's value with `{host}` where the host goes, and the host must end in one of `other.hosts`. tools-service refuses
any other value with a 400 when the app is turned on or an account is added, before any sign-in starts, so a typed
address never sends a person or a token outside the system. `GET /v1/apps/{id}` answers each setting's choices and
`other`, so the Connect window draws the question from the plugin. A choice with `test_account: true`, or a host ending
in one of `other.test_account_hosts`, starts the window's Test account switch on; the person can change it.

When the system refuses a sign-in, on the redirect back (`error`, `error_description`) or at the token exchange (the
token answer's `error`), `POST .../sign-in/complete` answers 422 `sign_in_refused` with `details: {message, who,
providerCode}` and records the refusal on the account, which then reads refused. `message` is the first
`sign_in_errors` entry whose `error` is the code and whose `description_contains`, when given, is in the description
(any case); `{app}` and `{credential}` in `say` are the app's title and the name of the app credential the account
signs in with. With no entry the platform says:

| Code | Says | Who |
|---|---|---|
| `access_denied` | `<App> access was not given. Connect again to retry.` | person |
| `invalid_client` or `incorrect_client_credentials`, at the token exchange | `The client secret for <credential> is wrong. Replace it on its Credentials page.` | admin |
| anything else | `<App> refused the sign-in: <description>` | person |

Salesforce, in the plugins repository:

```yaml
connection:
  sign_in_errors:
    - error: invalid_client
      description_contains: must be installed
      say: Your Salesforce admin needs to install Ops AI's app in your org first.
      who: admin
    - { error: OAUTH_APP_BLOCKED, say: Your Salesforce admin has blocked Ops AI's app. Ask them to allow it., who: admin }
settings:
  login_url:
    type: string
    title: Where do you sign in to Salesforce?
    default: "https://login.salesforce.com/services/oauth2"
    choices:
      - { value: "https://login.salesforce.com/services/oauth2", label: login.salesforce.com, hint: Production and developer orgs }
      - { value: "https://test.salesforce.com/services/oauth2", label: test.salesforce.com, hint: Orgs used for testing, test_account: true }
    other:
      label: Your company's address
      hint: Your Salesforce My Domain
      placeholder: acme.my.salesforce.com
      value: "https://{host}/services/oauth2"
      hosts: [.my.salesforce.com, .my.salesforce.test]
      test_account_hosts: [.sandbox.my.salesforce.com]
```

`ops plugin validate` refuses a choice whose value is not of the setting's type, an `other` with no `hosts`, a value
without `{host}` or a suffix without its leading dot, a `sign_in_errors` entry with no `say` or no `who`, and a
`credential_settings` name that is not a setting.

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

A worked example, added to the Ticket desk plugin from Start a new plugin: one tool that reads a queue's tickets and
counts the open ones, which a request template cannot do. The module sits beside the manifest:

```python
# src/ops_plugin_ticketdesk/tickets.py
from typing import Any

from ops_plugin_sdk import Context, tool


@tool(access="read")
def open_tickets_summary(ctx: Context, queue: str) -> dict[str, Any]:
    tickets = ctx.http.get(f"{ctx.settings.api_url}/queues/{queue}/tickets").json()["tickets"]
    open_ = [t for t in tickets if t["status"] == "open"]
    oldest = min((t["opened_at"] for t in open_), default=None)
    return {"queue": queue, "open": len(open_), "total": len(tickets), "oldest_open": oldest}
```

The manifest names it by its full import path. A short name such as `tickets:open_tickets_summary` is refused with
`cannot import tickets`:

```yaml
  - name: open_tickets_summary
    title: Summarize a queue
    description: How many tickets in a queue are open, and the oldest one
    access: read
    input:
      queue: { type: string, pattern: "^[a-z0-9-]{1,40}$", description: "The queue, such as billing" }
    function: ops_plugin_ticketdesk.tickets:open_tickets_summary
```

Its test answers the request the way the system would, through the same `call` as a request-template tool:

```python
def test_the_summary_counts_the_open_tickets_of_a_queue() -> None:
    def desk(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/queues/billing/tickets"
        return httpx.Response(200, json={"tickets": [
            {"status": "open", "opened_at": "2026-11-01"},
            {"status": "closed", "opened_at": "2026-10-01"},
            {"status": "open", "opened_at": "2026-10-20"},
        ]})

    client = Fake(httpx.Client(transport=httpx.MockTransport(desk)), "k-1")
    out = call(plugin, "open_tickets_summary", {"queue": "billing"}, SETTINGS, client)
    assert out == {"queue": "billing", "open": 2, "total": 3, "oldest_open": "2026-10-20"}
```

`validate` then counts 2 tools, and `test` reports 2 passed.

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
suite with the plugin's `src/` on the path, so a plugin in its own repository needs no install to be tested. A test
calls a tool as tools-service would with `ops_plugin_sdk.testing.call(plugin, tool, args, settings,
Fake(client, token))`, where `client` is an `httpx.Client` bound to a fake of the system, usually through
`httpx.MockTransport(handler)` with a handler that answers like the system (`tests/test_tools.py` in Salesforce,
`tests/fake_github.py` in GitHub).

`testing.call` builds the request with the same kit functions tools-service uses: each input left out as its
`default`, the plugin's and the tool's `headers` (a header naming an unset setting left out), then the bearer token,
which wins a name they share. A paged tool answers one page and a `next_cursor` that is the page state as plain JSON,
which a test passes back as `{"cursor": ...}`.

## Try a plugin on a local stack

A local stack calls a plugin's system the way it calls any outside system: over https on port 443, to a host on the
workspace's egress list. To point it at a fake of the system instead, serve the fake over https on this machine's
private address (not 127.0.0.1) with a certificate for the system's host names, then tell tools-service where those
names are and to trust that certificate. GitHub's `tests/fake_github.py` does the serving and prints what to set.

| Step | How |
|---|---|
| 1. Start the stack with sign-in and fakes | `make up AUTH=platform DEMO_MODEL=fake` |
| 2. Install the plugin | `uv run ops plugin install <plugin folder>`, then `make restart SVC=tools` and `make restart SVC=kb`, each with `AUTH=platform` |
| 3. Serve the fake | `uv run --directory services/tools-service python <plugin>/tests/fake_github.py --dir .run/fake-github`; it prints its address, certificate and host map |
| 4. Point tools-service at it | Write `OPS_EGRESS_EXTRA_CA=<certificate>` and `OPS_EGRESS_RESOLVE='{"github.test":"<address>","api.github.test":"<address>"}'` to `.run/demo-addons.env` (`.run/isolated/demo-addons.env` on an `ISOLATED=1` stack), then `make restart SVC=tools`. The stack reads that file after `.env` on every restart, and the map is used in development only |
| 5. Allow the hosts | As a Security admin, Settings › Security › Egress: Add host for each name, and Add range for `<address>/32` |
| 6. Turn it on and connect | Turn a plugin on, below, then the App's Connect window (apps.md) with the fake's client id and secret, and the system's settings pointed at the fake's names |

A person's browser opens the sign-in page at the fake's name too, which no DNS answers. In a browser test, route that
host to the fake's address, as `scripts/demo-salesforce/walk.mjs` does with `context.route`; by hand, add the names to
`/etc/hosts` with the fake's address and accept its certificate once.

To have an agent call a plugin's tool in chat on the fake model, grant the tool to the agent and send
`call <tool> {json}`, such as `call github_list_issues {"owner": "acme-logistics", "repo": "dispatch-api"}`: the fake
calls that tool with that JSON object as its input, then replies with the gist of the result (models.md, The test model). No real
model is needed.

## Install a plugin

| How | When |
|---|---|
| Put its folder in the install's plugins folder (`plugins/` in the repo, `OPS_PLUGINS_DIR` in Docker and Kubernetes) | Every plugin an install runs, built-in or brought by a customer |
| Add it to the environment tools-service runs in (`uv add`) | A packaged plugin on a developer's stack |
| List its folder in `OPS_PLUGIN_PATHS` (a JSON list) | A plugin under development, without copying it |

`ops plugin install <folder>` validates the plugin, then copies its package folder into the plugins folder (`--into`
names it when it is not `./plugins`), replacing an earlier copy whole; a plugin that fails validation is not copied.
`ops plugin remove <id>` deletes it. Restart tools-service and kb-service after either.

```
uv run ops plugin install ../ops-ai-plugins/plugins/salesforce
uv run ops plugin remove opsai.salesforce
```

Compose mounts the checkout's `plugins/` read-only at `/plugins` in tools and kb (`OPS_PLUGINS_HOST_DIR` names another
host folder), so `ops plugin install --into <that folder>` then a restart of both is the whole install.

### Plugins in a built image

The release image (`deploy/fly/Dockerfile`) ships the plugins `deploy/plugins.json` pins, in `/app/plugins`, which is
its `OPS_PLUGINS_DIR`. Each pin names a GitHub repository, a full commit and the plugin's folder in it:

```json
{"source": "https://github.com/chanl-ai/ops-ai-plugins", "ref": "<40-character commit>", "path": "plugins/salesforce"}
```

The build fetches each commit, validates the plugin as `ops plugin install` does and stops on any problem. A branch or
tag is refused, so an image built twice from the same commit holds the same plugins. To ship a newer plugin, change its
`ref` and rebuild; mounting another folder at `OPS_PLUGINS_DIR` replaces the baked ones. To bake them into a folder
yourself: `uv run python deploy/images/bake_plugins.py --into ./plugins`.

tools-service and kb-service load every plugin when they start. A plugin that fails validation is left out and logged
at start as `plugin_failed` with its error, and every other plugin still loads.

## Turn a plugin on

An install with no plugin loads nothing: the plugin routes answer 404 and kb-service refuses a plugin source
(`tools_unavailable`). A plugin that loaded is offered to every team: installing it is the platform admin's decision,
and taking it out of the plugins folder is how it is withdrawn. The team's switch, its settings and its sign-in are the App's Connect window in the console (apps.md,
Turn an App on); the calls below are the same steps for a script.

Ops AI's own OAuth app for a plugin, which every team uses unless it brings its own, comes only from the install
config. Register the app once with the vendor and set its client in the deploy's secret store:
`OPS_PLUGIN_CLIENTS='{"opsai.salesforce": {"id": "<client id>", "secret": "<client secret>"}}'`. tools-service reads
it at start and never writes the secret to the database; no route sets or shows it. A team's own client is kept once,
in `app_credentials`, and the accounts that sign in with it point at that row.

| Who | Call | What it does |
|---|---|---|
| Platform admin | install config `OPS_PLUGIN_LOCKED='{"opsai.salesforce": {"api_version": "61.0"}}'`, then restart tools-service | Fixes a lockable setting for every team; taking the plugin out of the plugins folder stops every team's calls, which then read "no longer installed" |
| Team admin (`connections.manage`) | tools-service `PUT /v1/apps/plugin:opsai.salesforce/team` with `{enabled, settings, signIn, kind, credentials, clientId, clientSecret}` | Turns it on for the team and makes the team's default account, whole, for its sign-in kind (below); off again keeps the account and settings |
| Team admin | `POST /v1/apps/plugin:opsai.salesforce/accounts` with `{name, sandbox: true, ...}` and the same sign-in fields | Adds a sandbox account (a Salesforce sandbox org, for example). Test runs use it; live runs never do. Its sign-in address and the instance its sign-in names are its own |
| Security | nothing for the plugin's own hosts | The hosts in the manifest's `egress` (rendered with the team's settings) are reached by that plugin's sign-in, token, test and tool requests without listing; no other call reaches them unlisted. Private, loopback, link-local and metadata addresses stay refused |
| Team admin | `POST /v1/apps/plugin:opsai.salesforce/accounts/{id}/sign-in`, then `/sign-in/complete` | Signs the team in; `from_token` settings are read from the token answer here and kept on that account |

The first turn-on makes the account in one call, whatever the plugin's kind. `kind` picks one of the plugin's
`connection.kinds` (the first when left out) and cannot change once the account exists (`kind_fixed`).
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
or My accounts, and calls act as them) or `person_or_team` (each person, with the team account as backup). A plugin
lists which of these it allows. One team's app, connection or token never serves another team, and one person's token
never serves anyone else.

On a connection each person signs in to, a key, password or token kind asks each person for their own: the
team gives the address and how the key is sent, and no key of its own. A person gives theirs with
`PUT /v1/me/accounts/{id}/credentials` and `{credentials: {key}}` (`{username, password}` for `basic`,
`{token}` for `bearer`), from the chat card that asks for it or from My accounts; it is sealed in their own row and
never answered back. `GET /v1/me/accounts?every=true` lists every account of the team a person can connect, with
`connected`, the method and the fields to give. A call acting for a person with no key is refused
`CONNECTION_NOT_LINKED` naming `authKind` and `personFields`, so the console asks for the key in place; a call with
nobody behind it is refused with reason `no_person`. A wrong key fails that person's call with the system's 401 and
leaves everyone else's working; Disconnect removes it.

After that, builders grant the plugin's tools to agents as any other tool, and a knowledge base adds a source with
`POST /v1/sources` and `{type: "tool", config: {plugin: "opsai.salesforce", source: "articles"}}`. Nobody can edit,
publish or delete the plugin's tool module; a new plugin version replaces it.

## Plugin updates

Behind the `plugin_updates` install flag (`OPS_FLAGS`), off by default; off, a plugin's tools are written once and
every team calls the installed manifest. On, each team runs the plugin version it took:

| What | How |
|---|---|
| The team's version | Its binding records the version, a digest of the tool declarations (the plugin-wide headers and each tool's manifest entry) and the declarations. A team takes the installed version when it turns the plugin on |
| An upgrade | The operator installs the new package and restarts tools-service. The account's tool row follows it, keeping each tool's id and a dropped tool as a switched-off row. Nothing changes for a team until it takes the update |
| Calls and lists | Built from the team's version: a changed tool keeps its request and inputs, a dropped one still answers and stays listed, a new one is neither listed nor callable. A Python tool always runs the installed package's function |
| The review | `GET /v1/apps/plugin:{id}/update`: both versions, and each new, changed and removed tool with its inputs added, removed and changed. agents-service's `GET /v1/tool-uses?tools=` names the team's agents and workflows that use each one |
| Taking it | `POST /v1/apps/plugin:{id}/update` with the installed digest the review was read at; another upgrade since then answers 409 `update_changed`. Keeping the current version is not taking it |

Not versioned per team: the sign-in (addresses, scopes, the lookup after sign-in), the endpoint and the egress hosts,
which are the installed version's. uc-609 (`make usecase-test UC=uc-609`) runs an upgrade from 0.1.0 to 0.2.0 across a
restart.

## Proof

Use cases uc-564 and uc-581 run all of this against a fake Salesforce on main: `make usecase-test UC=uc-564` and
`make usecase-test UC=uc-581`, then `make usecase-report UC=<id>` for their stories. uc-581 runs the seven query tools,
paging, the checks on query values, the sync's restart and the tools picker's titles. uc-588
(`make usecase-test UC=uc-588`) turns on one test plugin per sign-in kind from `services/tools-service/tests/plugin_kinds`
against `docs/usecases/lib/fake_multi_auth.py`, a person's own sign-in from chat, each person's own API key (steps
20-22), and a client certificate;
`docs/usecases/tools-service/scripts/evidence-uc-588-stripe.py` runs the bearer kind against Stripe in test mode.
uc-583 (`make usecase-test UC=uc-583`) turns on Entra, Google and DocuSign style plugins from
`services/tools-service/tests/plugin_signed` against `docs/usecases/lib/fake_token_endpoint.py`, which checks each
assertion as Entra does. uc-584 (`make usecase-test UC=uc-584`) runs the six fields of Headers, forms and sign-in steps
from `services/tools-service/tests/plugin_fields` against `fake_multi_auth.py`, and Salesforce's UserInfo lookup against
the fake Salesforce; `docs/usecases/tools-service/scripts/evidence-uc-584-stripe.py` sends a header, a form and an amount
limit to Stripe in test mode.

## Not built yet

| Gap | Today |
|---|---|
| A console page for the install's plugins and locked settings | Install config only (`OPS_PLUGINS_DIR`, `OPS_PLUGIN_LOCKED`); the team's switch and sign-in are the App's Connect window |
| An end-to-end use case in a plugin's own repository | A plugin repository has `ops plugin test`; end-to-end proof is ops-ai's use cases below, or a walk through Try a plugin on a local stack |
| Per-person access lists | Stored on the binding, not enforced |
| Adding a plugin knowledge source from the console | kb-service API only; the source page syncs and shows it |
| Plugins running out of process | Python tools run inside tools-service |
| Inbound webhooks a plugin declares | Designed; not built yet |
| One rate window per connection, Retry-After, and recorded fakes with standard cases | Planned |
| Knowledge items over 25 MB | Planned |
