# Staging on one Fly machine

Status: current (c-387). Staging runs from one image on one Fly app, `<your-app>-one`, at
https://<your-app>-one.fly.dev, against the staging database `<your-app>-db`. Deployed from 4d5a9e56 on
2026-10-20 by `make stg-deploy`: every process up and the click walk 41 of 41 OK, the first row of each list opened
(`.codeloop/evidence/387/stg-deploy-4d5a9e56.txt`). The fourteen per-service apps of `deploy/fly.md` are stopped, not
deleted, and stay the layout production can use. Files: `deploy/fly/`, `deploy/host/`.

## What runs

One machine, shared-cpu-2x with 4 GB, region ewr, volume `ops_ai_data` (1 GB) at `/data`. The process host
(`deploy/host/ops_host.py`) starts the processes of `deploy/fly/processes.toml` in order, waits on each one's ready URL,
restarts one that exits, and stops the machine when one exits more than five times in five minutes.

| Process | Command | Port | Public path |
|---|---|---|---|
| opa | `opa run --server` on tools-service's policy | 8181 | none |
| platform | `python -m ops_platform` | 8710, 8711 internal | `/api/platform/` |
| files | `python -m ops_files`, bytes in `/data/files` | 8750 | `/api/files/` |
| models | `python -m ops_models` | 8730 | none |
| fake | `python -m fake_openai`: the only model; answers from committed rules, calls no provider | 8746 | none |
| tools | `python -m ops_tools` | 8720 | `/api/tools/` |
| kb | `python -m ops_kb`, bytes in `/data/kb-files` | 8740 | `/api/kb/` |
| documents | `python -m ops_documents` | 8760 | `/api/documents/` |
| agents | `python -m ops_agents.api` | 8700 | `/api/agents/` |
| worker | `python -m ops_agents.api.worker` | none | none |
| console | `next start` | 3016 | `/` |
| caddy | `caddy run` (`deploy/fly/Caddyfile`), started last | 8080 | the origin |

The bank stand-in stays its own app, `<your-app>-bank` (stopped): workflows call it as an outside system at its
public URL. Start it with `fly machine start` before a levy run.

## Logins and keys

The machine holds every value the per-service apps held, staged by
`uv run python deploy/fly/staging/apps.py one-secrets --db ~/.config/ops-ai/staging-db-url.txt --admin
~/.config/ops-ai/staging-admin.env --logins ~/.config/ops-ai/staging-logins.env --models ~/.config/ops-ai/staging-models.env`
(values never printed).

| Secret | Who gets it |
|---|---|
| `OPS_DATABASE_URL` (the attach's superuser) | The release command only; `withhold` in `processes.toml` keeps it from every process |
| `OPS_DATABASE_URL_<SERVICE>` (`ops_<service>_runtime`) | That service as its `OPS_DATABASE_URL`; the worker uses agents' |
| `OPS_SVC_KEY_<SERVICE>` | That service as its signing key |
| `OPS_PLATFORM_SIGNING_KEY`, `OPS_REVIEW_KEY`, `OPS_SECRETS_KEY` | The services `deploy/images/service_keys.py` names |
| `OPS_MODELS_KEY_AGENTS`, `OPS_MODELS_KEY_DOCUMENTS` | agents and the worker, documents |
| `OPS_SERVICE_PUBLIC_KEYS`, `OPS_BOOTSTRAP_*` (password withheld) | Every process; the release command makes the first admin |

A process gets only what its `env` table names (`deploy/host/tests/test_ops_host.py`,
`test_a_withheld_secret_reaches_only_the_process_that_names_it`).

## Deploy

```
make stg-deploy              # REF=<sha> deploys another commit; SKIP_BUILD=1 reuses the pushed image
make stg-health              # every process, up or down
```

`deploy/fly/stg_deploy.sh` deploys from `git archive REF`, so uncommitted files never reach the image, and exits
non-zero on any failure:

| Step | What it does | Measured on 4d5a9e56 |
|---|---|---|
| Build | The `runtime` target on Fly's remote builder, pushed as `registry.fly.io/<your-app>-one:<sha>` | 31 s with the builder's cache, 177 s without |
| Deploy | The release command (`deploy/fly/release.sh`) migrates every chain as the superuser and makes the first admin; then the machine is replaced in place | 58 s |
| Grants | `grants.sql` from `make db-ddl` at REF on a throwaway local PostgreSQL 18, applied through `fly proxy` as the superuser | 38 s (49 s pulling the image) |
| Health | Polls `ops_host.py --check` over `fly ssh` until every process is up | 10 s |
| Walk | `docs/usecases/lib/stg_click_walk.mjs` with the first admin from `~/.config/ops-ai/staging-admin.env` | 136 s, 41 OK |

Build to every process up: about 2 minutes 20 seconds; with the walk, 4 minutes 33 seconds. The per-service deploy
took about 21 minutes across 14 apps.

## Idle, cold boot and memory

| Measure | Value | How |
|---|---|---|
| Cold boot, host start to Caddy | 28 s; agents up 6 s later | `[host] <name>: ready` lines in `fly logs` |
| Wake from stopped | First request answered 200 after 36 to 40 s; Fly's proxy holds it, no error | `fly machine stop`, then one `fetch` of `/login` timed |
| Peak memory during the walk | 1.54 GB in use of 4 GB | `MemTotal - MemAvailable` sampled each second on the machine |
| Largest processes | agents 278 MB, worker 250, tools 169, console 145, documents 134, files 132, kb 128, platform 116, models 100 MB RSS | `/proc/<pid>/status` after the walk |

`fly.toml` sets `auto_stop_machines = "stop"` and `min_machines_running = 0`: the machine stops when no request has
come for a few minutes, and the worker's timers do not run while it is stopped.

## Cost

Fly's ewr list prices (https://docs.fly.io/about/pricing): 2.19 USD a month per shared vCPU and 6.00 USD per GB of RAM
beyond 256 MB per vCPU. shared-cpu-2x with 4 GB is 25.38 USD a month if it never stops; stopped, only the volume
(0.15 USD per GB) and the root filesystem (0.15 USD per GB) are billed, so staging costs about 3.5 US cents per hour it
runs. The database stays at about 3.70 USD a month. The per-service apps came to about 34 USD a month always on at the
same prices (nine 256 MB and four 512 MB machines). **Unverified** against an invoice.

## The model

The models-service connection points at the fake on this machine, bound once after the first deploy:

```
fly ssh console -a <your-app>-one -C 'sh -c "cd /app && OPS_SERVICE_SIGNING_KEY=\$OPS_SVC_KEY_AGENTS \
  OPS_SERVICE_SIGNING_KID=svc-agents-1 /app/.venv/bin/python deploy/fly/connect_model.py \
  --models-url http://127.0.0.1:8730 --base-url http://127.0.0.1:8746/v1 --alias default --model fake-chat \
  --input-price 1 --output-price 1 --budget 5 --key-id purpose:agents"'
```

The existing keys stay. The per-service apps, if started again, need the same command run on `<your-app>-agents`
with `--base-url http://<your-app>-fake.internal:8746/v1`.

## Facts that shape it

| Fact | Consequence |
|---|---|
| Fly passes `release_command` to the image's entrypoint as arguments | `deploy/fly/entrypoint.sh` runs given arguments and starts the host only with none; otherwise the 512 MB release machine starts every service, runs out of memory and the deploy times out |
| `fly deploy` returns when the machine starts, before the host has started every process | The deploy command polls `--check` before the walk |
| `NEXT_PUBLIC_*` URLs are baked at build and must be absolute | The image is built for one origin: `[build.args] OPS_PUBLIC_ORIGIN` in `fly.toml` |
| Agents' health answers 503 until a model is bound | agents has a `check` URL, not a `ready` gate, so the console and Caddy start without waiting for it |
| A migration can add a table its runtime login cannot read | Every deploy applies `grants.sql` |

## Roll back, logs, stop

| Task | Command |
|---|---|
| Logs | `fly logs -a <your-app>-one`; each line starts with `[<process>]` |
| Roll back | `REF=<older sha> SKIP_BUILD=1 make stg-deploy` when that sha's image was pushed. Migrations do not roll back: roll back only to an image whose chains the database already has |
| Stop | `fly machine stop <id> -a <your-app>-one`; the next request starts it |

## Not covered

| Item | State |
|---|---|
| Files uploaded before the move | Copied on 2026-10-20 (c-406): `<your-app>-files` started, `/data/files/objects` tarred out over `fly ssh`, unpacked into the machine's `/data/files` without overwriting, the old machine stopped again. Before the copy their downloads answered 502 |
| One process for the Python services | Research: `.codeloop/specs/387-staging-runs-from-one-image-on-one-fly-m/research-process-layout.md` |
| Outgoing mail | `OPS_MAIL_PROVIDER=none` |
| The embed app | Not in the image |
| Processes run as root in the container | The per-service images run as uid 10001; this one does not yet |
