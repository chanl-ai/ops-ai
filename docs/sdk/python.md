# Python SDK

Status: current. Built and tested against the local stack; not yet published to PyPI, so install it from the
repository until the first release.

Call Ops AI from Python: start workflow runs and wait for them, decide the human tasks they open, and work with agents,
cases, tools, knowledge and files, as one person acting in one team.

## Install

```bash
pip install ./sdk/python        # from a clone of the repository, until the package is on PyPI
```

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

Arguments win over the environment, which wins over the profile the `opsai` CLI saves (`OpsAI(profile="builder")` names another). On a local stack with no proxy,
pass `services={"agents": "http://127.0.0.1:8700", ...}` to reach each service on its own port.

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

`list` walks every page. Each call returns the response's data as a dictionary typed from the API reference.

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
| `agents` | `tool_options(search)` (what may be granted), `grant_tools(id, tool_ids)` (kept beside the ones it holds) |
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

`opsai` ships with the Python package and uses the same saved sign-in as `OpsAI(profile=...)`. Add `--json` after the
verb for machine output.

| Command | What it does |
|---|---|
| `opsai kb create NAME [--owner]`, `set KB [--rerank on\|off] [--query-model] [--rewrite]`, `delete KB` | Make, tune and retire a knowledge base |
| `opsai kb add-source NAME --kb KB [--plugin P --source S --value NAME=ID]`, `scopes --plugin P --source S` | Add a source; list what its picker offers |
| `opsai kb push SOURCE --name N --title T --text TEXT` | Put one item into a push source |
| `opsai kb add-file KB [PATH...] [--file-id ID]` | Upload files, or take ones already in Files, and sync them |
| `opsai templates list [--kind] [--source]`, `install REF [--kind] [--fields]` | See the offered templates; add one as the team's copy |
| `opsai secrets list\|create NAME\|rotate NAME\|rename NAME NEW\|delete NAME` | The team's secrets; the value comes from `--value` or standard input |
| `opsai policies get\|set KEY [VALUE]` | The team's policies |
| `opsai egress list\|allow-host H\|allow-range R\|remove-host H\|remove-range R` | Hosts and ranges tools may reach |
| `opsai tools discover SPEC`, `import MODULE SPEC [--operation N]`, `request-review MODULE`, `create NAME --display-name N`, `decide-review REVIEW [--decision]`, `publish MODULE`, `run --module MODULE TOOL` | Take an OpenAPI document to a published module |
| `opsai agents tool-options [--search]`, `grant-tools ID TOOL...`; `opsai tasks approve TASK [--password]` | Grant tools to an agent; approve a held write |
| `opsai connectors list`, `connect APP [--link] [--account]`, `finish --state S --code C`, `accounts`, `disconnect APP` | Your own sign-ins on apps |

```bash
SOURCE=$(opsai kb add-source Policies --kb "$BRANCH" --json | jq -r .id)
opsai kb push "$SOURCE" --name fees/overdraft --title "Overdraft fees" --text "Fees are waived on the first day."
opsai kb add-file "$BRANCH" --file-id "$SHEET" --file-id "$MANUAL"
opsai templates install plugin:opsai.starters:doc-coauthoring
opsai connectors connect "Person desk"
```

## Errors

A refused call raises a subclass of `OpsError` with `status`, `code`, `message` and `request_id`: `BadRequest` (400,
422), `Unauthorized` (401), `Forbidden` (403), `NotFound` (404), `Conflict` (409), `RateLimited` (429) and
`ServerError` (5xx). Reads are retried twice on 429 and 5xx; a write is retried only when its route takes an
idempotency key and the call sends one.

## Asynchronous use

`AsyncOpsAI` has the same attributes with every call awaited, and `list` is an async iterator.

## Where it lives

The package is `sdk/python`; its lower layer, `ops_ai/_generated`, is written by `sdk/generate.py` from the services'
OpenAPI documents. `make sdk` regenerates it after a route changes, and `make sdk-check` fails until it is. The
example `sdk/python/examples/seed_team.py` seeds a fresh team end to end.
