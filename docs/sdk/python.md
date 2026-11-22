# Python SDK

Status: current, version 1.0.0.

Call Ops AI from Python: start workflow runs and wait for them, decide the human tasks they open, and work with agents,
cases, tools, knowledge and files, as one person acting in one team.

## Install

```bash
pip install ops-ai
```

The package holds the SDK and the `opsai` command line. It is not on the public package index yet (planned), so install
it from your company's package mirror or from a clone of the repository, as [Install the CLI](../guide/install-cli.md)
shows.

## Connect

Create an API key in the console under Settings > Team > API keys, in the team the script acts in.

```python
from ops_ai import OpsAI

ops = OpsAI(api_key="ok_...", base_url="https://ops.example.com", team="team_claims")
```

| Setting | Argument | Environment |
|---|---|---|
| Address of the deployment | `base_url` | `OPS_BASE_URL` |
| API key | `api_key` | `OPS_API_KEY` |
| Team the calls act in | `team` | `OPS_TEAM` |

Arguments win over the environment, which wins over the profile `opsai login` saves (`OpsAI(profile="builder")` names
another). On an install with no proxy in front, pass `services={"agents": "<address>", ...}` with each area's own
address.

## Run a workflow and decide its task

```python
started = ops.runs.start("wf_card_dispute", input={"cardholder": "Jordan Example", "amount": "120.00"})
run = ops.runs.wait(started["runId"])  # returns when the run ends or stops at a human task
if run.get("taskId"):
    ops.tasks.decide(run["taskId"], "approve", reason="Within the lead's limit.")
    run = ops.runs.wait(started["runId"])
print(run["status"], run.get("outcome"))
```

`runs.stream(run_id)` gives the run's events as they happen instead of waiting.

## What the client offers

| Attribute | Verbs |
|---|---|
| `agents`, `cases`, `connections`, `knowledge` | `list(**filters)`, `get(id)`, `create(body)` |
| `workflows`, `files` | `list(**filters)`, `get(id)` |
| `threads` | `list`, `get` (the thread's state), `create` |
| `teams` | `list` |
| `runs` | `list`, `get`, `start`, `wait`, `stream`, `cancel` |
| `tasks` | `list`, `get`, `decide`, `approve(task, decision=, password=)` (a held chat write is the chat's thread id; it asks the approver to confirm first) |
| `knowledge.search(body)`, `upload(name, content, mime=, purpose=)` | Search knowledge bases; upload a file |
| `raw.<service>.<operation>()` | Every other public operation, by its name in the API reference |

`list` walks every page, 50 rows at a time, so a loop over it sees every row. Each call returns the response's data as a dictionary typed from the API reference.

## Paging and filters

Every list takes the shared query: `page`, `page_size` (at most 50), `search`, `sort_by`, `sort_order` (`asc` or
`desc`), `ids` and the list's own filters, which take a list of values. The nouns' `list` passes them on and follows
every page. A `raw` operation returns one page as a dictionary with `data`, `pagination` and `facets`; read
`pagination["hasNext"]` to go on. The query and the reply are described on the [HTTP API](../reference/http-api.md#how-it-works) page.

```python
page = ops.raw.agents.agents_list_agents(page=1, page_size=20, sort_by="name", sort_order="asc", search="claims")
for agent in page["data"]:
    print(agent["name"])
if page["pagination"]["hasNext"]:
    more = ops.raw.agents.agents_list_agents(page=2, page_size=20, sort_by="name", sort_order="asc", search="claims")
```

The Apps area uses the words on the Apps page. An app is named by its id there (`plugin:<id>`, `builtin:<name>`, or a
custom app's connection id); an account is a connection id.

| Attribute | Verbs |
|---|---|
| `apps` | `list(connected=)`, `get(app)`, `turn_on(app, **fields)`, `turn_off(app)`, `users(app)` (who uses its tools), `add_custom(kind, name, base_address=, auth_kind=, secrets=)` |
| `credentials` | `set(app, client_id=, client_secret=)` (the team's own client), `test(app)` and `finish(app, state=, code=)` (Test with my account) |
| `accounts` | `connect(account)`, `test(account)`, `make_default(account)`, `mine()`, `set_key(account, key)`, `remove(account)` |
| `tools` | `list(app)`, `run(app, tool, input, real=)` (Mock reaches nothing; Real is the gateway's call); with no app, `list` and `get` are the tool modules' |
| `tools` (modules) | `discover(spec_url)`, `import_openapi(module, spec_url, operations=)`, `request_review(module)`, `review_of(detail)` and `decide_review(review, decision)` (Security's answer; `approved` publishes), `create_module(name, display_name)`, `publish_version(module)`, `run_module(module, tool, input, real=)` |
| `secrets` | `list()`, `create(name, value)`, `rotate(name, value)`, `rename(name, new_name)`, `delete(name)`; no answer carries a value |
| `policies` | `get(key)`, `set(key, value)`: the team's policies a Security admin changes, such as `toolWritesNeedApproval` (use `with_team` to act in another team) |
| `egress` | `list()`, `allow_host(host)`, `allow_range(cidr)`, `remove_host`, `remove_range`; Security admins only |
| `agents` | `update(id, fields, base=)` (saves fields on the draft, naming the copy last read; refused with `stale_base` when it has been saved since), `tool_options(search)` (what may be granted), `grant_tools(id, tool_ids)` (kept beside the ones it holds), `references(search, for_agent=)` (what a brief can mention with `@`), `add_reference(id, kind, ref_id)` (grants it as a new draft; a skill brings its tools and knowledge bases), `publish_check(id)` (what stops the draft from publishing, each with its field). `apply` carries `brief`, `promptMode` and `patterns`: a file with a `brief` has its role and instructions written from it |
| `resources` | `list(app)`, `add(resource)` (a copy in the team) |
| `usage` | `list(**filters)`: this team's tool calls |

## Knowledge, templates and connectors

| Attribute | Verbs |
|---|---|
| `knowledge` | `add_base(name, owner=)`, `add_source(name, kb_ids, type="push")`, `add_page(kb_id, title, text)` (the same title saves a new version), `push(source_id, name, title=, text=)` (the same name and text again answers `unchanged`) |
| `templates` | `list(kind=, source=)`, `install(template, kind=, **fields)`: the team's own copy of a template |
| `me.connectors` | `list()`, `connect(app, link=, account=, team=)` (returns `authorizeUrl`), `finish(state, code, error=)`, `accounts()`, `disconnect(app, account=)` |

```python
base = ops.knowledge.add_base("Branch procedures", owner="branch.ops@harborpine.example")
source = ops.knowledge.add_source("Policies", [base["id"]])
ops.knowledge.push(source["id"], "fees/overdraft", title="Overdraft fees", text="Fees are waived on the first day.")

made = ops.templates.install("plugin:opsai.starters:doc-coauthoring")  # made["created"] is True the first time

start = ops.me.connectors.connect("Person desk")  # open start["authorizeUrl"] in a browser
ops.me.connectors.finish(state, code)             # the state and code in the address the browser returned to
```

## The command line

`opsai` ships with this package and uses the same saved sign-in as `OpsAI(profile=...)`. Every area and verb is on
[the opsai command line](../reference/cli.md) page.

Moving from 0.1.0: see [Upgrading to 1.0.0](upgrading.md).

## Errors

A refused call raises a subclass of `OpsError` with `status`, `code`, `message`, `request_id` and `details`: `BadRequest` (400,
422), `Unauthorized` (401), `Forbidden` (403), `NotFound` (404), `Conflict` (409), `RateLimited` (429) and
`ServerError` (5xx). The fields come from the API's one error body, described on the [HTTP API](../reference/http-api.md#how-it-works) page. Branch on `code`, and quote
`request_id` when asking for help.

```python
from ops_ai import NotFound

try:
    ops.agents.get("agt_missing")
except NotFound as e:
    print(e.status, e.code, e.request_id)
```

Reads are retried twice on 429 and 5xx; a write is retried only when its route takes an idempotency key and the call
sends one.

## Asynchronous use

`AsyncOpsAI` has the same attributes with every call awaited, and `list` is an async iterator.

## Next

<!-- site: cards -->
- **[TypeScript SDK](typescript.md)**: The same client for Node and the browser.
- **[HTTP API](../reference/http-api.md)**: The routes under every call, for `raw` operations.
- **[Upgrading to 1.0.0](upgrading.md)**: Paging, closed bodies and the one error format.
