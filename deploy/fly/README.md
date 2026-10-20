# Fly

Staging runs one Fly app per image (`staging/`), runbook `docs/deploy/fly.md`. The one-image app (`fly.toml`,
`processes.toml`) is the earlier plan, still buildable locally: `docs/deploy/fly-staging.md`.

| File | Role |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | Every image: one target per service, console, OPA, proxy, and `runtime` (the one-image app) last |
| `staging/apps.py`, `staging/*.toml` | The staging apps, sizes and settings in one table; it writes the configs and stages each app's secrets |
| `Caddyfile` | One origin: `/` the console, `/api/<service>/` each browser-facing service; upstreams from `OPS_UPSTREAM_*` |
| `fly.toml`, `processes.toml`, `entrypoint.sh`, `env.sh`, `release.sh` | The one-image app: host, processes, DSN, migrations |
| `generate_keys.py` | The signing, review and secrets keys an install outside dev needs |
| `connect_model.py` | Binds an alias to a provider model and issues a capped model key (`--key-id` per service) |
| `smoke.mjs` | Walks any install's origin: sign-in, chat, upload, a workflow run, a document read, three console pages |
