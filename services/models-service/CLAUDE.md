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
| `src/ops_models/providers.py`, `connection_settings.py` | Provider adapters (openai-compatible, Azure OpenAI, scripted) and the rules a connection's settings must meet |
| `src/ops_models/provider_keys.py` | Account provider keys, sealed, never returned |
| `src/ops_models/seed.py` | The dev seed: scripted connection, `bank-*` aliases, model keys `mk_dev_agents`, `mk_dev_extract`, `mk_dev_tools_check` and one per agent |
| `src/ops_models/store/` | All database code; `store/provider_keys.py:20` names the tenant role `ops_models_tenant` |
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
| Apply the chain | `make migrate` |
| Logs and health | from the root: `make logs SVC=models FOLLOW=0`, `make health` |

## Try it as a person

```bash
make api GET /v1/models/providers AS=admin SVC=models
make api GET /v1/provider-keys AS=admin SVC=models
```

Aliases, keys and the call log (`/v1/models/aliases`, `/v1/models/keys`, `/v1/models/calls`) answer service tokens
only, so `make api` as a person gets 401 there. Reference:
[make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| Every completion is logged | One `model_call_log` row per authenticated completion, a refusal included, with no text |
| Order of checks | Key status, expiry and budget, rate limit, alias, cleared sensitivity, then image clearance, then the provider call |
| Refusals | In the platform error envelope, which OpenAI clients read as `error.code` (`key_budget_exhausted`, `images_not_cleared`, `provider_key_missing`, ...). A provider's failure is classified once, in `providers.py` `PROVIDER_FAILURES` (`provider_unreachable`, `provider_timeout`, `provider_auth_failed`, `provider_rate_limited`, `provider_bad_request`, `provider_error`); its message never quotes the provider's body |
| Versions are immutable | A change to an alias is a new version; the newest current one serves |
| Real calls | Tests and use cases use the scripted provider or the fake OpenAI; real calls are capped per experiment |

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/models-service/overview.md](../../docs/services/models-service/overview.md) | Connections, aliases, keys, admission, completions, Azure OpenAI |
| [docs/guide/models.md](../../docs/guide/models.md) | Setting up models on an install |
| [docs/usecases/models-service/](../../docs/usecases/README.md) | 3 use cases |
| [openapi.json](openapi.json) | The API |

Known differences: the overview's status line says `make up` does not start this service; `make up` starts it
(`scripts/stack.sh:23`), and `make health` lists it.
