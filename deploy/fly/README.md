# Fly

Two layouts from the same images. `make stg-deploy` drives the one-machine app (`fly.toml`, `processes.toml`), runbook
`docs/deploy/fly-staging.md`. The one-app-per-image layout (`staging/`) is the one production can use, runbook
`docs/deploy/fly.md`.

| File | Role |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | Every image: one target per service, console, OPA, proxy, and `runtime` (the one-image app) last |
| `staging/apps.py`, `staging/*.toml` | The staging apps, sizes and settings in one table; it writes the configs and stages each app's secrets |
| `Caddyfile` | One origin: `/` the console, `/api/<service>/` each browser-facing service; upstreams from `OPS_UPSTREAM_*` |
| `fly.toml`, `processes.toml`, `entrypoint.sh`, `env.sh`, `release.sh` | The one-image app: host, processes, DSN, migrations |
| `generate_keys.py` | The signing, review and secrets keys an install outside dev needs |
| `connect_model.py` | Binds an alias to a provider model and issues a capped model key (`--key-id` per service) |
| `smoke.mjs` | Walks any install's origin: sign-in, chat, upload, a workflow run, a document read, three console pages |

## Working here

| Task | Command |
|---|---|
| Deploy, roll back, check staging | `make stg-deploy [REF=]`, `make stg-rollback [TO=]`, `make stg-health`; app names from your `staging.env` (`staging.env.example`) |
| Rewrite the per-image app configs after editing `staging/apps.py` | `uv run python deploy/fly/staging/apps.py write`; `order` prints the deploy order |
| Walk any install | `OPS_SMOKE_EMAIL=… OPS_SMOKE_PASSWORD=… node deploy/fly/smoke.mjs <origin>` |

Never write a real app name, org or host into these files. Folder rules: `../CLAUDE.md`.
