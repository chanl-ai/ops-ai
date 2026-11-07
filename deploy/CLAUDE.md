# Deploy: working rules

Status: current.

`deploy/` holds everything that runs Ops AI outside a developer's stack: the images every target starts, the
targets themselves (Compose, Kubernetes, Fly, the one-command install, the release package), the schema as scripts a
DBA applies, and the checks that prove each target installs and walks. It owns no product behaviour: a service's code,
settings and migrations live in `services/` and `packages/`, and `deploy/` only packages and starts them. Folder
overview: [README.md](README.md). Design: [service map, "Deployment targets"](../docs/architecture/service-map.md).

Shared rules (onion order, the one local stack, targeted tests, commit hooks) are in the root guide and are not
repeated here: [onion order](../CLAUDE.md#onion-order), [one local stack](../CLAUDE.md#one-local-stack),
[tests](../CLAUDE.md#tests), [commits](../CLAUDE.md#commits), [folder guides](../CLAUDE.md#folder-guides), and the
make layout in [docs/architecture/make.md](../docs/architecture/make.md).

## What lives here

| Path | Owns | Guide |
|---|---|---|
| `images/` | What every image runs at start: entrypoint, migration order (`chains`), first admin, health check, console start, plugin baking | [images/CLAUDE.md](images/CLAUDE.md) |
| `fly/Dockerfile` | Every image, one build target per service plus `console`, `opa`, `proxy`, `db-scripts`, `test-mssql` and `runtime` (the one-image app) | [fly/README.md](fly/README.md) |
| `compose/` | `app.yaml` (the install as containers) with `build.yaml`, `dba.yaml`, `try.yaml`, `mailbox-demo.yaml` overlays; `compose.yaml` (the dev stack's PostgreSQL, OPA and mail servers) | [compose/README.md](compose/README.md) |
| `k8s/` | Kustomize base written by `generate.py`, overlays `example` and `kind`, per-service Secrets | [k8s/README.md](k8s/README.md) |
| `fly/` | Staging on Fly: the one-machine app (`fly.toml`, `processes.toml`) that `make stg-deploy` drives, and the per-image apps (`staging/apps.py`) | [fly/README.md](fly/README.md) |
| `host/` | `ops_host.py`, the process host that runs the services `OPS_ENABLED_SERVICES` names on one machine | [host/README.md](host/README.md) |
| `database/` | The schema as DBA scripts: baseline, guarded upgrades, drift, roles and grants, the SQL Server golden DDL | [database/README.md](database/README.md) |
| `install/` | `install_api.py`, the steps of `../install.sh` that need Python, run inside an image | [install/README.md](install/README.md) |
| `release/` | The versioned package a client team installs with no checkout, the multi-platform image build | [release/README.md](release/README.md) |
| `devhost/` | A Coder template for a shared dev VM, one workspace per developer from `.devcontainer/` | [devhost/README.md](devhost/README.md) |
| `mirror-test/` | The behind-a-company-mirror lane: a clean install through a local Nexus on a closed network | [mirror-test/CLAUDE.md](mirror-test/CLAUDE.md) |
| `plugins.json` | The plugins every image ships with, each pinned to a full commit; `images/bake_plugins.py` reads it | [docs/guide/plugins.md](../docs/guide/plugins.md) |
| `vm/` | Does not exist yet. The VM target (systemd units, native PostgreSQL, no container runtime) is designed only | [service map](../docs/architecture/service-map.md) |

## How the targets fit together

Every target starts the same images, built from `fly/Dockerfile`, and differs only in how it supplies settings,
secrets and the database.

| Concern | One source | Read by |
|---|---|---|
| Images | `fly/Dockerfile` targets; `release/images.sh` builds them from `git archive` of one commit | `compose/build.yaml`, `k8s/proof.sh`, Fly, `release/package.sh`, `.github/workflows/release-images.yml` |
| Migrations | `images/chains` (agents, tools, models, kb, platform, files, documents) and `images/migrate.sh` | compose's migrate job, Fly's release command (`fly/release.sh`), the k8s migrate Job, `database/schema.py` |
| Settings every service shares | `x-settings` in `compose/app.yaml` | `k8s/generate.py`, which writes them into the base ConfigMap, so the two cannot disagree |
| Keys per service | `images/service_keys.py` (which keys each service uses); `fly/generate_keys.py` makes them | `fly/staging/apps.py`, `k8s/write_secrets.py`, `fly/processes.toml` |
| Database logins | one login per service, owning only its tables (`database/` baseline, grants) | every target; the superuser migrates and no running process holds it |
| Policy | OPA, loaded from `services/tools-service/policy` | a container in compose and k8s, a process on Fly |
| One origin | `fly/Caddyfile`: `/` the console, `/api/<service>/` each browser-facing service | the `proxy` image (compose, k8s, per-image Fly apps) and the `caddy` process on the one-machine app |

Rules that hold for every target:

- A release must run on one virtual machine with no container runtime, on PostgreSQL alone. Nothing here may add a
  dependency that only exists as a container.
- Settings come from `OPS_*` environment values or from files under `/run/secrets` named after the setting
  (`images/entrypoint.sh`); no target writes a `.env` into an image, and no env file is committed.
- A target never hands a service a key or login it does not use; add a key to `images/service_keys.py` first, then
  every target picks it up.
- A new service needs its build target in `fly/Dockerfile`, its chain in `images/chains`, its row in
  `k8s/generate.py` and `fly/staging/apps.py`, its process in `fly/processes.toml`, and its keys in
  `images/service_keys.py`.

## Make targets that act on deploy/

Run from the repo root; `make help` lists them with their arguments.

| Target | Runs | Safe to run locally |
|---|---|---|
| `make db-ddl SERVER=<url>`, `db-upgrade-sql FROM=<ref>`, `db-drift`, `db-release` | `database/schema.py` against a throwaway server you name | Yes, against a throwaway server; never the stack's database |
| `make db-ddl-golden` | Rewrites `database/golden/mssql/` from the store models | Only after reviewing the model change it records |
| `make db-scripts-proof FROM=<ref>` | `database/proof.sh` on its own PostgreSQL container (:15499) | Yes; slow, needs Docker |
| `make release-package TAG=<ref>` | `release/package.sh`: images, bundle, tarball, checksums in `dist/` | Slow; builds every image |
| `make release-proof PACKAGE=…` | `release/proof.sh`: installs a tarball alone and walks it | Slow |
| `make install-proof` | `release/install_proof.sh`: a fresh clone through `./install.sh` on GHCR images | Slow; pulls images |
| `make release-tag` | `scripts/release-tag.sh`; `DRY=1` prints the tag name only | Pushes a tag without `DRY=1` |
| `make stg-deploy`, `stg-rollback`, `stg-health` | `fly/stg_deploy.sh` on the app named by `STG_APP` in your staging config | Changes a live Fly app |
| `make uc-sql-server` | `fly/mssql/run-usecases.sh` on a SQL Server test machine | Starts paid machines |
| `make qa-mirror`, `mirror-down` | `mirror-test/lane.sh` | Yes; its own compose project, slow |

Staging app names come from `$OPS_STAGING_CONFIG/staging.env` (default `~/.config/ops-ai/staging.env`, template
`fly/staging.env.example`); `fly/stg_env.sh` refuses any app outside `STG_APP_PREFIX`. The repository holds no app
name, org or host.

## Tests and proofs

| Check | Command | Where it runs |
|---|---|---|
| DBA script tests (offline SQL renders, SQL Server golden files, runtime logins, isolation markings) | `uv run pytest -q deploy/database/tests` | `make verify` (`pool-deploy` in `make/python.mk`), CI |
| k8s secret writer | `uv run pytest -q deploy/k8s/tests` | `make verify`, CI |
| k8s base is what `generate.py` writes | `uv run python deploy/k8s/generate.py --check` | `make python-verify`, CI |
| Process host | `uv run pytest -q deploy/host/tests` | Nowhere automatically: neither `pool-deploy` nor CI runs it, so run it after changing `host/` |
| Compose install end to end | `sh deploy/compose/proof.sh` (`KEEP=1`, `BUILD=0`) | By hand; project `ops-compose` on :18890 |
| Mailbox demo on the release images | `sh deploy/compose/mailbox_proof.sh` | By hand |
| Kubernetes on kind | `sh deploy/k8s/proof.sh` (`KEEP=1`, `BUILD=0`) | By hand; localhost:18891 |
| DBA scripts | `make db-scripts-proof` | By hand |
| Any install's origin | `OPS_SMOKE_EMAIL=… OPS_SMOKE_PASSWORD=… node deploy/fly/smoke.mjs <origin>` (acts in a test team; use a fake model unless spend is intended) | Every proof above, and after a staging deploy |

The proofs start their own databases and compose projects on their own ports and never touch the dev stack. After a
migration lands, run `uv run pytest -q deploy/database/tests` before committing: the golden files and the offline SQL
check fail on a revision SQL Server cannot render.

Broken on the current checkout: `deploy/database/tests` has 4 failures. The SQL Server golden files for agents and
tools stop at earlier revisions than the chains (`test_mssql_ddl.py`, fixed by `make db-ddl-golden` after review), and
agents revision `0099_review_asker_is_person` does not render as offline SQL (`test_offline.py`).

## Generated files

| File | Written by | Check |
|---|---|---|
| `k8s/base/**` | `uv run python deploy/k8s/generate.py` | `generate.py --check` |
| `fly/staging/<app>.toml` | `uv run python deploy/fly/staging/apps.py write` | none; regenerate after editing `apps.py` |
| `database/golden/mssql/*.sql` | `make db-ddl-golden` | `database/tests/test_mssql_ddl.py` |
| `dist/` | `release-package`, `db-ddl`, `db-release` | gitignored |

Edit the generator, regenerate, and commit both; never hand-edit a generated file.

## Reference docs

| Topic | Doc |
|---|---|
| Compose install | [docs/deploy/compose.md](../docs/deploy/compose.md) |
| One-command install, upgrade, backup, behind a mirror | [docs/deploy/install.md](../docs/deploy/install.md) |
| Release package and its install guide | [docs/deploy/release-package.md](../docs/deploy/release-package.md), [docs/deploy/install-guide.md](../docs/deploy/install-guide.md) |
| Kubernetes | [docs/deploy/kubernetes.md](../docs/deploy/kubernetes.md) |
| Fly, one app per image | [docs/deploy/fly.md](../docs/deploy/fly.md) |
| Fly, one machine (what `make stg-deploy` runs) | [docs/deploy/fly-staging.md](../docs/deploy/fly-staging.md) |
| DBA scripts and SQL Server | [docs/deploy/database.md](../docs/deploy/database.md) |
| Shared dev host | [docs/deploy/devhost.md](../docs/deploy/devhost.md) |
| Mailbox demo | [docs/deploy/demo-mailbox.md](../docs/deploy/demo-mailbox.md) |
| Docs site hosting | [docs/deploy/docs-site.md](../docs/deploy/docs-site.md) |
