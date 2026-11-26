# Staging on one Fly machine

Status: current. A staging copy can run from one image on one Fly app, `<your-app>`, at
https://<your-app>.fly.dev, against a database app `<app-prefix>-db`. Measurements below come from one deploy by `make stg-deploy`: every process up and the click walk 41 of 41 OK, the first row of each list opened. The fourteen per-service apps of `deploy/fly.md` are stopped, not
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
| models | `python -m ops_models` | 8730 | `/api/models/v1/` for the settings routes only (provider keys, connections, provider types, aliases) |
| fake | `python -m fake_openai`: the only model; answers from committed rules, calls no provider | 8746 | none |
| tools | `python -m ops_tools` | 8720 | `/api/tools/` |
| kb | `python -m ops_kb`, bytes in `/data/kb-files` | 8740 | `/api/kb/` |
| documents | `python -m ops_documents` | 8760 | `/api/documents/` |
| agents | `python -m ops_agents.api` | 8700 | `/api/agents/` |
| worker | `python -m ops_agents.api.worker` | none | none |
| console | `next start` | 3016 | `/` |
| caddy | `caddy run` (`deploy/fly/Caddyfile`), started last | 8080 | the origin |

The bank stand-in stays its own app, `<app-prefix>-bank` (stopped by default): workflows call it as an outside system at its
public URL. Start it with `fly machine start` before a court order run.

## Logins and keys

The machine holds every value the per-service apps held, staged by
`uv run python deploy/fly/staging/apps.py one-secrets --db <private-dir>/staging-db-url.txt --admin
<private-dir>/staging-admin.env --logins <private-dir>/staging-logins.env --models <private-dir>/staging-models.env`
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

## The demo team and the test teams

Staging has one tenant ("Ops AI staging"); platform-service has no route that makes a second one, so the boundary is
the team. A team is the data boundary: another team's records answer 404 on every route.

| Team | Id | What it holds | Who belongs |
|---|---|---|---|
| Harbor & Pine Operations | `team_a0877a1d8907` | The demo: the seeded bank's agents, handbooks, skills, guardrails, workflows (the dispute intake `northfield_card_dispute_intake`; the court order workflows `*_a0877a1d`, which `mailbox_demo.py levy` makes, since `--no-levy` leaves them out of the seed), runs, cases and chats, and the court order story by mailbox | admin@, builder@ and approver@demo.example with their roles, demo@example.com (viewer), the seed's four bank staff, the first admin |
| Security | `team_security` | The workspace Security team: egress, secrets, the bank module and the platform tools; test leftovers from earlier walks | The first admin, approver@example.com, admin@demo.example (admin, for the mailbox and its secret) |
| Customer Operations | `team_319b708e5de1` | A test team: the first seed and probe records; its handbooks renamed "(Customer Operations test team)" | The seed's four bank staff, the first admin |

Walks and probes act in a test team and remove what they make where a route allows:

| Walk | Team | Cleanup |
|---|---|---|
| `deploy/fly/smoke.mjs` (run by `make stg-deploy` after the click walk; `make stg-smoke` runs it alone; `SKIP_SMOKE=1` leaves it out) | `OPS_SMOKE_TEAM` (`STG_ROLES_TEAM` in a deploy, as the roles team's admin); default the admin's first team | Deletes its agent, workflow (archived when it has runs), files, chat and approver, also when a request throws, and the approvers and agents named like its own that an earlier failed run left. Its invite changes the workspace's permission version, so every token issued before it is refused once (`permissions_changed`); the walk renews its own session right after and the console renews on the next call |
| `docs/usecases/lib/stg_click_walk.mjs` | The first admin's first team; it only reads | None needed |
| `scripts/team_isolation_probe.py --seed` | The team given as B (use `team_319b708e5de1`) | Deletes what it seeded; a case has no delete route and stays |

Install or refresh the demo team with the sample team installer (every line FOUND on a second run):

```
OPS_DEMO_MEMBER_PASSWORD=<phone password> OPS_DEMO_TOOL_APPROVER_PASSWORD=<Security approver password> \
uv run python scripts/sample_team.py install --origin https://<your-app>.fly.dev --admin-env <env file> \
  --name "Harbor & Pine Operations" --workflow-prefix northfield_ --no-levy \
  --member admin@demo.example:admin --member builder@demo.example:builder --member approver@demo.example:approver \
  --tool-access mod_3a1fdc1ba8a4 --tool-access-team team_security \
  --tool-approver approver@example.com
```

The env file names the first admin (`OPS_BOOTSTRAP_ADMIN_*`), `OPS_DEMO_PASSWORD`, `OPS_DEMO_MODEL_ALIAS=fake` and
`OPS_DEMO_LIVE_MODEL_ALIAS=default`, so the agents answer people on the real model once the install ends
(`scripts/sample-team/admin.env.example`). `scripts/check_demo_team.py` proves each login's role in the team and that
a test team's record is absent from it. `--tool-access` grants the team's workflows the Security team's bank module; the platform tools need no grant, since no team owns them.

### Role accounts

Staging runs with `OPS_ENVIRONMENT = "production"` (`deploy/fly/fly.toml`), so platform-service seeds no people and
accepts no shared password: the dev people of `services/platform-service/seed/dev-roles.json` do not exist here and
answer 401. Staging has its own account for each member role (admin, builder, approver, viewer, chat_user) in one team,
kept in `~/.config/ops-ai/staging-roles.env` (template `deploy/fly/staging-roles.env.example`; the GitHub secret
`STAGING_ROLES_ENV` on a runner). Emails and passwords are never printed.

| To | Do |
|---|---|
| Make the accounts the install lacks and sign in as each | `make seed-roles ENV=staging` (safe to run again; `make stg-deploy` runs the same seed and check after the signed-in request, and fails the deploy on any FAIL line) |
| Only check, changing nothing | `make roles-check ENV=staging` |
| Call the API as a role | `make api GET /v1/me ENV=staging AS=builder` (`team-admin`, `builder`, `approver`, `viewer`, `chat_user`; `admin` stays the first admin) |
| Walk the console as roles | `node scripts/agents/ui_walk.mjs --origin https://<your-app>.fly.dev --as admin,builder,viewer,chat_user --routes /agents` (runs the seed first; `member` names the viewer) |
| Change an account's password | Reset it in the console, put the new one in the file, then update the `STAGING_ROLES_ENV` secret with the file's contents |

A deploy never invents an account: a role with no lines in the file fails the deploy before the walk, naming
`make seed-roles ENV=staging`, which on a person's machine makes the address and password and appends them. After that,
copy the file into the `STAGING_ROLES_ENV` secret. The same targets with no `ENV` check a local or preview stack, whose
people platform-service seeds at boot; `make up` runs it.

Records with no delete route stay in the test teams (cases, chats, runs, reviews, document types).

## Deploy

App names are not in the repo. `make stg-deploy`, `stg-rollback` and `stg-health` read them from
`~/.config/ops-ai/staging.env` (or `$OPS_STAGING_CONFIG/staging.env`); copy `deploy/fly/staging.env.example` there and
fill in `STG_APP`, `STG_DB_APP` and `STG_APP_PREFIX`. A missing file stops the command with a message naming the example.
The deploy refuses any app whose name does not start with `STG_APP_PREFIX` (default `<your-app>`). The `.toml` files
carry `<your-app>` or `<app-prefix>` placeholders; the deploy fills them in and passes `-a`.

```
make stg-deploy-ci REF=develop   # on GitHub (deploy-staging.yml), the usual way
make stg-deploy              # from this machine; REF=<sha> deploys another commit; SKIP_BUILD=1 reuses the pushed image
make stg-health              # every process, up or down
make stg-smoke               # the smoke check alone against staging, no deploy; writes to staging, so the owner runs it
```

`deploy/fly/stg_deploy.sh` deploys from `git archive REF`, so uncommitted files never reach the image, and exits
non-zero on any failure:

| Step | What it does | Measured on 4d5a9e56 |
|---|---|---|
| Build | The `runtime` target on Fly's remote builder, pushed as `registry.fly.io/<your-app>:<sha>` | 31 s with the builder's cache, 177 s without |
| Deploy | The release command (`deploy/fly/release.sh`) migrates every chain as the superuser and makes the first admin; then the machine is replaced in place | 58 s |
| Grants | `grants.sql` from `make db-ddl` at REF on a throwaway local PostgreSQL 18, applied through `fly proxy` as the superuser | 38 s (49 s pulling the image) |
| Health | Polls `ops_host.py --check` over `fly ssh` until every process is up | 10 s |
| OCR | `deploy/fly/check_ocr.py` on the machine: fails unless Tesseract has English data and documents-service's `/health` does not report OCR missing | not measured |
| Plugins | `deploy/images/bake_plugins.py --check` against the app's `OPS_PLUGINS_DIR`: fails unless the plugins match `deploy/plugins.json` by id and version | not measured |
| Signed in | The first admin signs in through the origin and lists agents: platform issues the session, agents-service verifies it | not measured |
| Role accounts | `deploy/fly/role_accounts.py seed`: invites the member-role accounts the install lacks, then signs in as each and checks the role it holds | 4 of 5 signed in on the first read-only check; the chat user is made by the first deploy |
| Walk | `docs/usecases/lib/stg_click_walk.mjs` with the first admin from `<private-dir>/staging-admin.env`; `SKIP_WALK=1` leaves out the walk and the smoke check after it | 136 s, 41 OK |
| Smoke check | `deploy/fly/smoke.mjs` as the roles team's admin (`STG_ROLE_ADMIN_*` in `staging-roles.env`) in `STG_ROLES_TEAM`: makes, publishes and runs an agent, a workflow, files and a document read, opens three console pages, removes what it made, and ends on one `smoke:` line; `SKIP_SMOKE=1` leaves out only this step. A failed check fails the deploy, and on GitHub a failure after the machine was replaced rolls the deploy back | 17 s, 13 checks |

The image installs Tesseract with English data (`tesseract-ocr`, `tesseract-ocr-eng`), and `fly.toml` sets
`OPS_KB_OCR` and `OPS_ATTACHMENTS_OCR` to `auto`, so scanned pages in knowledge sources and chat attachments are read by
OCR. A deploy whose image lost Tesseract stops at the OCR step instead of letting every scan fail quietly.

Build to every process up: about 2 minutes 20 seconds; with the walk, 4 minutes 33 seconds. The per-service deploy
took about 21 minutes across 14 apps.

### Deploy on GitHub: deploy-staging.yml

`.github/workflows/deploy-staging.yml` is the way to deploy staging. It runs `make stg-deploy REF=<commit>` on a runner
(through `.github/actions/stg-deploy`), one deploy at a time (concurrency group `staging-deploy`: a run that is waiting
is replaced by a newer one, a running one finishes). It starts two ways:

| Trigger | When | Pin |
|---|---|---|
| A merge to `develop` | `ci.yml` job `staging` calls it once `ci-ok` passed for that commit | Not deployed, and the `staging` job fails red, while a `release/*` or `hotfix/*` branch exists on origin or a live `STAGING_HOLD` is set (docs/deploy/release.md, The staging hold) |
| A push to `release/*` or `hotfix/*` | The same job | Not frozen by a branch: it is the release being tested. A live `STAGING_HOLD` still stops it and fails the job, whatever the ref |
| By hand | `make stg-deploy-ci REF=<branch, tag or commit>` (`SKIP_WALK=1`, `REASON=`), or Actions, deploy-staging, Run workflow | Deploys anyway; the summary says which pin it overrode |

| To | Do |
|---|---|
| Put another commit, tag or branch on staging | `make stg-deploy-ci REF=<ref>`; it starts the run and watches it to the end |
| Keep it there through later merges | Set the repository variable `STAGING_HOLD` to `X.Y.Z: reason` (the release it waits for; ignored once tag `vX.Y.Z` exists); merges are still checked but not deployed |
| Test a release on staging | After telling the owner, `make stg-deploy-ci REF=release/current`; a push to the train deploys nothing, so set `STAGING_HOLD` for as long as the owner tries it. A numbered `release/X.Y.Z` or any `hotfix/*` branch on origin still freezes merges to `develop` (`docs/deploy/release.md`) |
| Go back to `develop` | Delete the hotfix branch after its merge and clear `STAGING_HOLD`; the next merge to `develop` deploys, or `make stg-deploy-ci` now |

`REF` is what is deployed; the workflow file runs from `develop` (`WORKFLOW_REF=` changes that). GitHub offers a
hand-started run only for a workflow that is also on the default branch, `main`, so the button and `make stg-deploy-ci`
work once `deploy-staging.yml` has reached `main` in a release; until then use `make stg-deploy` from a machine. A commit
whose image an earlier release pushed is not built again (`SKIP_BUILD=1`). After the deploy the job checks every
process, OCR, plugins and one signed-in request (the first admin signs in and lists agents), then the click walk and the
smoke check, which `skip_walk` leaves out together. If a step fails after the machine was replaced, the job runs `make stg-rollback TO=<the release
before>` without the walk and fails either way; a failure before that point leaves staging as it was. The job summary
shows the commit, the trigger, the reason, any pin it overrode, the URL, each step's seconds, the walk's counts, the smoke
check's last line (passed and failed counts, and the step and reason when a request stopped it) and the rollback's result. A release is only tagged, by `release-tag.yml`, on the merge into `develop`.

The local pin (`staging-pin` in the config folder, written by `repo.sh snapshot`) still stops `make stg-deploy` on the
owner's machine; the runner has no such file, so it lists the release and hotfix branches on origin (`git ls-remote`) and reads `STAGING_HOLD` instead.

The job runs in the GitHub environment `staging` (Settings, Environments) and fails, naming what is missing, while any of
these is unset. The variables are the app names, written into `staging.env` on the runner; the secrets are written to
the files `stg_deploy.sh` reads and never printed:

| Secret or variable | Value |
|---|---|
| `vars.STG_APP` | `<your-app>` |
| `vars.STG_DB_APP` | `<app-prefix>-db` |
| `vars.STG_APP_PREFIX` | Optional: `<app-prefix>`; names must start with it (default `<your-app>`) |
| `FLY_API_TOKEN` | Two deploy tokens joined by a comma: `<your-app>` (build, deploy, ssh, releases) and `<app-prefix>-db` (the grants proxy) |
| `STAGING_DB_URL` | The contents of `<private-dir>/staging-db-url.txt` |
| `STAGING_ADMIN_ENV` | The contents of `<private-dir>/staging-admin.env` |
| `STAGING_ROLES_ENV` | The contents of `<private-dir>/staging-roles.env` (one account per member role) |

The runner installs Chromium (`playwright install --with-deps chromium`) for the click walk.

```
fly tokens create deploy -a <your-app> -n "github ops-ai staging" -x 8760h
fly tokens create deploy -a <app-prefix>-db -n "github ops-ai staging grants" -x 8760h
```

Not yet run on GitHub: the call from `ci.yml` with the environment's secrets, a hand-started run, the comma-joined
token, `fly ssh console` and `fly releases` with a deploy token, the pin check and the rollback are proven on the first
runs after merge.

### Production on GitHub: not built yet

No workflow deploys production. A tag `vX.Y.Z` is made by `release-tag.yml` on the develop merge of a release or hotfix pull request; nothing deploys
it. A workflow that read a repository variable could not prove that a person approves each deploy, since the
environment's reviewers and the place the deploy token lives are invisible to it. Before one returns, the owner sets up:

| Item | Setting |
|---|---|
| Environment | A `production` environment (Settings, Environments) with required reviewers, and deployment tags limited to `v[0-9]*` |
| Deploy token | `FLY_API_TOKEN` for the production app as a secret of that environment only, never a repository secret |
| Other values | The production app's names as environment variables, and its database address and first-admin file as environment secrets |
| Token for the tag push | A tag pushed with the repository's own token starts no workflow; a token that does, or a hand-started run with the tag |

The workflow's first job, before the job that names the environment, reads the environment's protection rules through the
API and stops unless required reviewers are set and the tag pattern is `v[0-9]*`. It then checks that the tag is on `main`
and that a staging release ran the same tree. The deploy job is `.github/actions/stg-deploy` aimed at the production
apps, so it runs migrations, grants, the process checks and the click walk as staging does.

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

Fly's list prices (https://docs.fly.io/about/pricing): 2.19 USD a month per shared vCPU and 6.00 USD per GB of RAM
beyond 256 MB per vCPU. shared-cpu-2x with 4 GB is 25.38 USD a month if it never stops; stopped, only the volume
(0.15 USD per GB) and the root filesystem (0.15 USD per GB) are billed, so staging costs about 3.5 US cents per hour it
runs. The database stays at about 3.70 USD a month. The per-service apps came to about 34 USD a month always on at the
same prices (nine 256 MB and four 512 MB machines). **Unverified** against an invoice.

## The model

The models-service connection points at the fake on this machine, bound once after the first deploy:

```
fly ssh console -a <your-app> -C 'sh -c "cd /app && OPS_SERVICE_SIGNING_KEY=\$OPS_SVC_KEY_AGENTS \
  OPS_SERVICE_SIGNING_KID=svc-agents-1 /app/.venv/bin/python deploy/fly/connect_model.py \
  --models-url http://127.0.0.1:8730 --base-url http://127.0.0.1:8746/v1 --alias default --model fake-chat \
  --input-price 1 --output-price 1 --budget 5 --key-id purpose:agents"'
```

The existing keys stay. The per-service apps, if started again, need the same command run on `<app-prefix>-agents`
with `--base-url http://<app-prefix>-fake.internal:8746/v1`.

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
| Logs | `fly logs -a <your-app>`; each line starts with `[<process>]` |
| Roll back | `make stg-rollback` (the release before) or `TO=<older sha>`; `make stg-deploy-ci REF=<older sha>` does it on GitHub without a build when that sha's image was pushed. Migrations do not roll back: roll back only to an image whose chains the database already has |
| Stop | `fly machine stop <id> -a <your-app>`; the next request starts it |

## Not covered

| Item | State |
|---|---|
| Files uploaded before the move | Copied once when moving to one machine: `<app-prefix>-files` started, `/data/files/objects` tarred out over `fly ssh`, unpacked into the machine's `/data/files` without overwriting, the old machine stopped again. Before the copy their downloads answered 502 |
| One process for the Python services | Measured before staging moved to one machine |
| Outgoing mail | `OPS_MAIL_PROVIDER=none` |
| The embed app | Not in the image |
| Processes run as root in the container | The per-service images run as uid 10001; this one does not yet |
