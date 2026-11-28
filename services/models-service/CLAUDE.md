# models-service: working rules

Status: current.

The models service (`ops_models`, :8730; the console calls it the AI gateway) is the only way a model call leaves the
platform. It owns provider connections and the account's provider keys, bank aliases and their immutable versions,
model keys (one per agent, workflow, person or purpose) with budgets, spend and rate limits, admission, and a call
log that holds metadata only, never prompt or completion text. Callers send OpenAI-shaped requests to
`POST /v1/models/chat/completions` with a model key; no worker holds a provider credential.

Whether an alias reaches a real or a fake model is decided by its connection's base URL, which is data. `make up`
runs it with `OPS_MODELS_FAKE_OPENAI_URL` pointing at the fake OpenAI (`scripts/fake_openai`, run as `fakeai` on
:8746), and `make demo-model` moves the demo aliases between the fake and a real model. Shared service rules:
[services/CLAUDE.md](../CLAUDE.md). Cross-folder rules: [root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_models/app.py` | Every route (`create_models_app`): admin and admission routes on the service token, provider keys and connections for account admins, completions on the model key |
| `registry/providers/*.json`, `src/ops_models/registry.py` | One entry per provider type, read and checked at start-up; `OPS_MODELS_PROVIDER_REGISTRY_EXTRA` names a folder of more |
| `src/ops_models/providers.py`, `sigv4.py`, `connection_settings.py` | The adapters an entry names (`ADAPTERS`: openai-compatible, Azure OpenAI, Bedrock, scripted) and the rules a connection's settings must meet |
| `catalog/models.json`, `catalog/knobs.json`, `src/ops_models/catalog.py` | The pinned model facts (`models.json`) and the knob table (`knobs.json`: each provider's knobs, ranges and defaults, and how a model's facts narrow them); `ranges_for` builds a model's knobs from both, `fit` holds every call to the alias's model |
| `scripts/sync_catalog.py` | Refreshes the catalog snapshot (model facts only, no ranges) from models.dev and LiteLLM (`make catalog-sync`); review and commit the diff |
| `src/ops_models/provider_keys.py` | Account provider keys, sealed, never returned |
| `src/ops_models/seed.py` | The dev seed: scripted connection, `bank-*` aliases, model keys `mk_dev_agents`, `mk_dev_extract`, `mk_dev_tools_check` and one per agent |
| `src/ops_models/store/` | All database code; `store/provider_keys.py:20` names the tenant role `ops_models_tenant`, which provider keys, connections and alias reads run as |
| `scripts/fake_openai/` | A keyless stand-in for OpenAI's chat API, driven by `seed/demo-fake-openai/script.json` |
| `migrations/` | Its own chain, version table `alembic_version_models` |
| `tests/` | Admission, keys, providers, Azure, the fake OpenAI's rules, row isolation; no real model call |

Usage, price and budget arithmetic is `packages/ops_metering`; this service does the I/O around it.

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Serve in the foreground on :8730 | `make run` (seeded in dev). Stop the `make up` copy first with `scripts/stack.sh stop models` from the root: this Makefile's `stop` answers "not started" |
| Its tests | `make test`, or from the root `make test PKG=services/models-service` |
| One test file | `PYTEST_ADDOPTS=tests/test_dev_seed.py make test`: this Makefile ignores `T=` |
| Lint, types, OpenAPI | `make lint`, `make typecheck`, `make openapi-check` (`make openapi` to regenerate) |
| Refresh the model catalog | `make catalog-sync` (network), then review and commit `catalog/models.json` |
| Apply the chain | `make migrate` |
| Logs and health | from the root: `make logs SVC=models FOLLOW=0`, `make health` |

## Try it as a person

```bash
make api GET /v1/models/providers AS=admin SVC=models
make api GET /v1/provider-keys AS=admin SVC=models
make api GET /v1/models/provider-types AS=admin SVC=models
```

Keys and the call log (`/v1/models/keys`, `/v1/models/calls`) answer service tokens only, so `make api` as a person
gets 401 there; aliases also answer an account admin. Reference:
[make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| Every completion is logged | One row per authenticated completion, a refusal included, with no text: in the named tenant's `model_call_log` (held to it by the database), or `model_calls_untenanted` when the call names no tenant (kept for operators; no route lists it). A key's caps read `model_key_spend`, written in the same transaction; its day and run rows are swept 14 days after their last call (`models_spend_retention` on `/health/background`) |
| A billed call is charged once | After the provider answers, the settle writes the call's row and every ledger (key spent, tenant share, period totals) in one transaction, then once more as an `error`/`settle_failed` row if that fails, both under one call id (the row's primary key). When both fail, or the server stops before a settle ends, the whole charge is logged at error level (`model_call_row_lost`, `model_call_settle_unfinished_at_stop`) and nothing durable holds it. Replay those log lines once the database is back: `uv run python -m ops_models.recovery < lines.jsonl` (`recovery.py`). A line for a call already charged writes nothing, so replaying a line twice, or one whose commit landed, is safe. Log lines mask emails and long digit runs, so a line whose values were masked (a `user:<email>` key, a model name with a date) is refused, not replayed: put the real values back in it, then replay. There is no settling sweep and no pending row before the provider call |
| Order of checks | Key status, expiry and budget, rate limit, alias, cleared sensitivity, then image clearance, then the provider call |
| Refusals | In the platform error envelope, which OpenAI clients read as `error.code` (`key_budget_exhausted`, `images_not_cleared`, `provider_key_missing`, ...). A provider's failure is classified once, in `providers.py` `PROVIDER_FAILURES` (`provider_unreachable`, `provider_timeout`, `provider_auth_failed`, `provider_rate_limited`, `provider_bad_request`, `provider_error`); its message never quotes the provider's body |
| Versions are immutable | A change to an alias is a new version; the newest current one serves |
| A provider is data first | A new provider type is a registry entry; an adapter is added only when no existing one speaks its API, registered by name in `ADAPTERS`. No route branches on a type |
| Knobs | One rule, `catalog.fit`, on every completion: unsupported knobs left out, numbers clamped to the model's range. The runtime reads the catalog only from the committed snapshot |
| Real calls | Tests and use cases use the scripted provider or the fake OpenAI; real calls are capped per experiment |

## Known traps

- A billed call whose settle fails twice => log the whole charge with a replay command; the call's row stays and one charge per call is tested
- A migration that adds an index a later revision also adds => guard the create and the drop with exists checks; a database that ran the first lacks it going down
- An alias write => it needs `install.manage`, held by Owner; a test acting as another role gets a refusal
- A new `GET` route => add its row to `budgets.toml`, and open no second transaction in its session check; `tests/test_statement_budget.py` fails any route without a row
- A new read of provider connections or aliases => run it in `self.tx()` with `providers.mine()` or `aliases.ours()` in the query; an install-wide read lets one account see, re-point or call another account's connection
- A store change (tables, repositories, migrations, queries) pushed after `make ci-local` alone => ci-local lists `store-mssql` as skipped, so run `deploy/database/mssql_remote.sh test services/models-service -q <tests>` before the push

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/models-service/overview.md](../../docs/services/models-service/overview.md) | Connections, aliases, keys, admission, completions, Azure OpenAI |
| [docs/guide/models.md](../../docs/guide/models.md) | Setting up models on an install |
| [docs/usecases/models-service/](../../docs/usecases/README.md) | 6 use cases |
| [openapi.json](openapi.json) | The API |

Known differences: the overview's status line says `make up` does not start this service; `make up` starts it
(`scripts/stack.sh:23`), and `make health` lists it.

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`), [API contracts and models](../../docs/architecture/standards/api-and-models.md) (`AP1` to `AP7`, `MD1` to `MD4`), [data access](../../docs/architecture/standards/data-access.md) (`DA1` to `DA13`), [tenant isolation and access](../../docs/architecture/standards/tenancy-and-access.md) (`TN1` to `TN5`, `AC1` to `AC5`), [errors, logging and observability](../../docs/architecture/standards/observability.md) (`OB1` to `OB6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
