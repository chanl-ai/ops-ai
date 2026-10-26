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

Arguments win over the environment, which wins over the profile the `ops` CLI saves. On a local stack with no proxy,
pass `services={"agents": "http://127.0.0.1:8700", ...}` to reach each service on its own port.

## Run a workflow and decide its task

```python
started = ops.runs.start("wf_card_dispute", input={"cardholder": "Jordan Example", "amount": "120.00"})
run = ops.runs.wait(started["runId"])               # returns when the run ends or stops at a human task
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
| `workflows`, `tools`, `files` | `list(**filters)`, `get(id)` |
| `threads` | `list`, `get` (the thread's state), `create` |
| `teams` | `list` |
| `runs` | `list`, `get`, `start`, `wait`, `stream`, `cancel` |
| `tasks` | `list`, `get`, `decide` |
| `knowledge.search(body)`, `upload(name, content, mime=, purpose=)` | Search knowledge bases; upload a file |
| `raw.<service>.<operation>()` | Every other public operation, by its name in the API reference |

`list` walks every page. Each call returns the response's data as a dictionary typed from the API reference.

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
