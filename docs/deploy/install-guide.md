# Install and operate Ops AI

Status: current. How to install, run and maintain Ops AI on your own machines. The full client guide adds the architecture, data, security and deployment options.

<!-- Generated from docs/guide/install.md and docs/guide/operate.md by scripts/docs/build_guide.mjs; edit those, then run the build. The full guide is docs/deploy/client-install-guide.html. -->

## Install

<!-- The steps below are included from docs/deploy/install.md, the install script's guide, when the page and
INSTALL.md are built; edit them there. -->

One script installs Ops AI on a machine with Docker from a clone of the repository, asks a few questions, checks the
result, and later upgrades, backs up, restores and reports on the same install ([Operate](#operate)). It pulls the
published images by default; a release's offline image file, or a build from source, serves a machine with no
registry access.

The published images are at `ghcr.io/chanl-ai/ops-ai`.

### Before you start

| Item | What you need | Details |
|---|---|---|
| A host | One Linux machine with Docker Engine 24 or newer, Docker Compose 2.22 or newer, curl and tar, 4 GB of memory for the containers and 15 GB of free disk | [Sizing](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/deployment-options.md#sizing) |
| A DNS name and TLS | A name such as `ops.example.com` on your load balancer or reverse proxy, forwarding to the port the script asks for | [The network](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/deployment-options.md#the-network) |
| PostgreSQL | For a trial, the script's built-in database. For real use, your own PostgreSQL 15 or newer: either a login that may change the schema, or DBA mode, where your DBA applies the scripts the install writes | [Data and database](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/data-and-database.md) |
| A model endpoint | Any OpenAI-compatible endpoint and its key; the built-in test model will do for a first look | [Models](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/models.md) |
| The first admin | A name and email address for the person who signs in first and invites everyone else | |
| Sign-in and outbound hosts | Your identity provider's OIDC or SAML details, and the hosts Ops AI will call, for the Security admin to set after the install | [Security and governance](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/security-and-governance.md) |

### Install

```bash
git clone https://github.com/chanl-ai/ops-ai.git
cd ops-ai
./install.sh
```

The host needs Docker 24 or newer, Docker Compose 2.22 or newer, curl, tar, 4 GB of memory for containers and 15 GB
of free disk. Python is not needed: the steps that use it run inside the images. The preflight names anything missing
and stops.

It asks these questions. Each has a default, a flag, and a key for an answers file (`--answers <file>`, one
`KEY=value` per line), so CI can run it unattended with `--yes`.

| Question | Default | Flag | Answers key |
|---|---|---|---|
| Port on this machine | 8890 | `--port` | `PORT` |
| Public URL | `http://localhost:<port>` | `--public-url` | `PUBLIC_URL` |
| Compose project name | `ops-ai` | `--project` | `PROJECT` |
| Organisation name | My organisation | `--org` | `ORG_NAME` |
| First admin's email and name | `admin@example.com`, First Admin | `--admin-email`, `--admin-name` | `ADMIN_EMAIL`, `ADMIN_NAME` |
| First admin's password (12+ characters) | generated, kept in `ops-ai.env` | `--admin-password-file` | `ADMIN_PASSWORD` |
| Database | `builtin`: a PostgreSQL 17 container, for a trial | `--database builtin` or `--database postgresql://user:pass@host:5432/db` | `DATABASE` |
| Database mode (own PostgreSQL only) | `auto`: the migrate job applies the schema with the given login | `--db-mode auto` or `--db-mode dba` | `DB_MODE` |
| Model | `test`: the built-in test model | `--model test` or `--model <OpenAI-compatible base URL>/v1` with `--model-name` and `--model-key-file` | `MODEL`, `MODEL_NAME`, `MODEL_API_KEY` |
| Image version | the checkout's version tag, else `deploy/release/version` | `--version` | `VERSION` |

What it does, in order:

1. Pulls `ghcr.io/chanl-ai/ops-ai/<image>:<version>` (linux/amd64 and linux/arm64). `--build` builds them from the
   checkout's HEAD instead; `--offline <images.tar.gz>` loads a release package's image file.
2. Writes `ops-ai.env` (mode 600) from `deploy/compose/app.env.example` and generates every key with the platform
   image's `generate_keys.py`. No secret is printed.
3. In `dba` mode, copies the release's PostgreSQL scripts to `./dba/postgres` (from the `db-scripts` image), writes
   `./dba/1-server.sql` with each service login's password, prints three `psql` commands for the DBA, waits, and checks
   each service's schema version before going on. The DBA runs them as the server admin; the schema is owned by
   `ops_migrator`, and no container gets a login that may change it.
4. Starts the database, migrations and services, connects the model, then starts the agents, worker, console and proxy,
   waiting for every health check. A provider key is saved as the account's model provider key `MODEL_PROVIDER_KEY`
   through models-service's API, never in `ops-ai.env`; models-service reads it by that name.
5. Runs the check: health through the published port, the console's sign-in page, a sign-in as the first admin, one
   read from every service through the proxy, and agents' health (a model is connected). Then it prints the URL and
   how to sign in.

Running `./install.sh` again on a working install checks it, says "nothing changed" and changes nothing. On an install
that is not running, it reuses `ops-ai.env` and its keys and starts it. It never makes new keys over existing ones:
`OPS_SECRETS_KEY` unlocks the stored credentials.

### The other commands

| Command | What it does |
|---|---|
| `./install.sh status` | Version, image source, database and model; each container's state; the check |
| `./install.sh logs [service]` | The last 200 lines, followed on a terminal |
| `./install.sh backup [--out DIR]` | One `.tar.gz` in `./backups/` (mode 600): a `pg_dump` of the database, the files and knowledge volumes, and `ops-ai.env` |
| `./install.sh restore <file>` | Stops the services, recreates the database from the dump, puts the volumes back, starts and checks. Refuses a backup made with another `OPS_SECRETS_KEY` |
| `./install.sh upgrade [--version V]` | At the same version: checks and changes nothing. Otherwise: backs up, gets the new images, applies the schema (auto) or writes `./dba/upgrade-<from>-to-<to>/` for the DBA and waits, restarts, checks, and on a failed check restores the backup on the old version |
| `./install.sh uninstall` | Asks, then removes the containers; asks again before deleting the volumes. Keeps `ops-ai.env` |

In `dba` mode, `backup`, `restore` and `upgrade` need an admin login that may dump the database, given as a file:
`--admin-url-file <file holding postgresql://admin:password@host:5432/db>`. A runtime login cannot dump it (row-level
security); without the file the script stops and says to ask the DBA.

### What is proven and what is not

| Claim | Evidence |
|---|---|
| Clone to signed in, images pulled from GHCR | `install_proof.sh` steps 1 to 3, run with `SIGNED_IN=1` (a registry login) while the packages are internal; the anonymous run waits for them to be public (**unverified**) |
| Every console page loads | `docs/usecases/lib/stg_click_walk.mjs`, steps 4 and 7 |
| A rerun and a same-version upgrade change nothing | steps 5 and 6: `ops-ai.env` checksum and container ids unchanged |
| Backup and restore | step 7: a table and a file made after the backup are gone after the restore |
| A failed upgrade rolls back | step 8b: a release whose console exits; exit 1, back on the old version, status passes |
| DBA mode, provider key through Settings > Model providers | step 9: PostgreSQL 17 with TLS and an admin that is not a superuser; the three printed commands; backup and restore with `--admin-url-file` |
| An upgrade across two releases that changes the schema | **unverified**: 0.1.0 is the first release. The auto path is the migrate job `compose.md` already proves; the DBA path renders Alembic's offline SQL from the recorded revisions (`deploy/install/install_api.py`) |
| A Linux server | **unverified**: the proof ran on Docker Desktop for macOS |

Images and the version: `deploy/release/version` names the version a checkout installs. A version tag `v<version>`
runs `.github/workflows/release-images.yml`, which builds every image for both platforms with
`deploy/release/images.sh` and pushes `<version>` and `latest`. The same script builds the release package's images
(`release-package.md`) and `--build`.

### Behind a company mirror

A company that serves packages from its own mirror (Sonatype Nexus, Artifactory or similar) can build and install Ops AI
without a download from the open internet. Every download in this repository goes through one setting below; a setting
left empty keeps the public address. Every locked version is at least 30 days old, which is the age most mirrors
require, with two named exceptions in `pnpm-workspace.yaml` until 2026-10-30 (streamdown 2.7.0 and remend 1.4.0).

| Setting | What it moves | Where it is read |
|---|---|---|
| `UV_DEFAULT_INDEX` | Python packages: the PyPI "simple" index of the mirror, ending in `/simple` | uv; `scripts/install_via_mirror.sh`; Docker build argument of the same name |
| `NPM_CONFIG_REGISTRY` | npm packages, including the console's fonts (they are npm packages, not a Google Fonts fetch) | pnpm; Docker build argument of the same name |
| `COREPACK_NPM_REGISTRY` | the pnpm release `package.json` names, which corepack downloads | corepack; Docker build argument of the same name |
| `UV_PYTHON_DOWNLOADS` | uv never fetches a Python by itself (`python-downloads = "manual"` in `pyproject.toml`); use the image's or the system's Python 3.12 | uv |
| `UV_PYTHON_INSTALL_MIRROR` | an explicit `uv python install 3.12`, used only by the Dockerfile's database-scripts stage | Docker build argument |
| `OPS_RUNNER_WASM_URL` | the 26 MB CPython-for-WASI file the code-tools runner needs; its SHA-256 is still checked | `python -m ops_runner.fetch`; Docker build argument |
| `PLAYWRIGHT_DOWNLOAD_HOST` | browser downloads for `playwright install`; only the UI use-case tests need a browser, so it is optional (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` skips it) | Playwright |
| `OPS_BASE_IMAGE_PREFIX` | a registry prefix ending in `/` for every third-party image: PostgreSQL, OPA, the mail test servers, and the Dockerfile's base images (`IMAGE_REGISTRY` build argument) | `deploy/compose/*.yaml`, `deploy/compose/build.yaml`, `deploy/fly/Dockerfile` |
| `OPS_IMAGE_REGISTRY` | where `install.sh` pulls the Ops AI release images, when they are mirrored (default `ghcr.io/chanl-ai/ops-ai`) | `install.sh` |
| `APT_MIRROR`, `APK_MIRROR` | Debian and Alpine package sources used while building images | Docker build arguments |
| `TIKTOKEN_CACHE_DIR` | not a mirror setting: tiktoken downloads its encoding file on first use from a public blob store; vendor the file and point this at it (`docs/architecture/dependencies.md`) | tiktoken, at run time |

The Compose build passes each setting through (`deploy/compose/build.yaml`); a plain `docker build` takes them as
`--build-arg`. A URL with a user name and password is visible in `docker history` of the build stage that uses it, so
give the build an anonymous read-only repository.

#### Developer workspaces

The devcontainer (`.devcontainer/`) and the shared-host template (`deploy/devhost/`) take the same settings. In a
devcontainer, set them in the shell that opens it or in `.devcontainer/.env.local`; the compose file passes them to the
image build and to the workspace, where `make install` reads the mirror whenever `UV_DEFAULT_INDEX` is set. On the shared
host, push the template with `--variable 'mirror_settings={...}'` and `--variable base_image_prefix=...`
(`deploy/devhost/README.md`). Node comes from the Node image, not from nodejs.org, and the devcontainer's Node feature
(a download from GitHub's registry) is gone.

#### Installing the locked versions through the mirror

`uv sync --frozen` downloads each file from the address `uv.lock` records (`files.pythonhosted.org`), which a mirror does
not serve. `make install-mirror` reads only the versions and hashes from the lock and fetches the files from
`UV_DEFAULT_INDEX`, rejecting any file that is not the locked one; pnpm already reads its registry from
`NPM_CONFIG_REGISTRY`. It sets `UV_NO_CONFIG`, because `exclude-newer` in `pyproject.toml` needs upload times and a
mirror whose index sends none (Nexus's PyPI proxy is one) then offers no version of anything.

```
export UV_DEFAULT_INDEX=https://nexus.example.com/repository/pypi-proxy/simple
export NPM_CONFIG_REGISTRY=https://nexus.example.com/repository/npm-proxy/
export COREPACK_NPM_REGISTRY=$NPM_CONFIG_REGISTRY
make deps-doctor           # which locked versions the mirror does not serve
make deps-relock MIRROR=1  # only when it named some: lock inside what it does serve, then run fast tests
make install-mirror
```

`make deps-doctor` asks the mirror for every locked package and prints the package, the locked version, the HTTP status
of that version's file and the newest version the mirror serves, for the packages it does not serve. Credentials in a
registry URL are masked in all output. It exits 1 when any package is blocked and writes `.mirror/constraints.txt` and
`.mirror/npm-overrides.json`. `make deps-relock MIRROR=1` locks every package to its locked version except those, then
installs and runs the fast tests (`scripts/deps_smoke.sh`). Its `uv.lock` and `pnpm-workspace.yaml` are for that
machine: they name the mirror's file URLs, so do not commit them.

| Check | Evidence |
|---|---|
| A clean install of both lockfiles through Nexus, on a network that reaches only Nexus, then 180 fast tests | `make qa-mirror` (`deploy/mirror-test/`), a nightly lane of the QA runner |
| Every locked version is at least 30 days old | `scripts/deps_audit.py age`, in the lane: Nexus's free edition has no age rule, so the lane enforces it |
| No critical advisory (CVSS 9.0 or higher) and no AGPL or GPL licence outside `deploy/mirror-test/audit-baseline.txt` | `scripts/deps_audit.py vulns` (osv-scanner; Sonatype OSS Index too when `OSSINDEX_TOKEN` and `OSSINDEX_USER` are set) and `licenses` |
| `deps-doctor` names a package the mirror blocks, and the relock succeeds | Run by hand on 2026-10-27 against the lane's Nexus with six 1.17.0 blocked by a routing rule (`deploy/mirror-test/nexus.sh block`): the doctor named it (403, newest served 1.16.0), the relock moved six to 1.16.0, the install and 180 tests passed. Not part of the nightly lane |
| A mirror that is not Nexus | **unverified**: the lane runs Nexus 3.70.4 only |

### By hand

Every step the script runs can also be run by hand: the Compose files and settings in
[Ops AI on Docker Compose](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/compose.md), the DBA's scripts in
[The database](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/database.md), and a Kubernetes install in [Ops AI on Kubernetes](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/kubernetes.md).

## Operate

How to check, upgrade, back up, restore and scale an Ops AI install. The install script's commands come first; the
manual commands after them are the fallback, and the ones Kubernetes uses.

Run the script's commands from the clone the install ran in; they read its settings from `ops-ai.env` there. In the
manual commands, `$C` is the Compose command for your install, for example
`docker compose -p ops-ai -f deploy/compose/app.yaml -f deploy/compose/dba.yaml --env-file ops-ai.env`, and `ops-ai`
is the Kubernetes namespace.

### Status and health

| Check | With the script | By hand: Compose | By hand: Kubernetes | Healthy |
|---|---|---|---|---|
| Everything at once | `./install.sh status`: version, image source, database and model, each container's state, then the install's check | | | The check passes |
| Every container | | `$C ps` | `kubectl -n ops-ai get pods` | Each service `Up (healthy)` or `Running` and ready; the migrate job exited 0 |
| The entry point | | `curl -fsS https://<your host>/api/platform/v1/health` | Same | `{"status":"ok"}` |
| Sign-in | Open your address and sign in | | | The console opens |

| Service | Health route | What it proves |
|---|---|---|
| platform | `/v1/health` | Process up |
| agents | `/health` | Process up, database reachable, and a model connected: it answers 503 until one is |
| worker | a database query | Process up and database reachable |
| tools | `/health` | Process up, and the policy engine serves the gateway's own policy: it answers 503 `policy_drift` otherwise |
| models, kb, files, documents | `/health` | Process up |
| console | `/login` | The console serves |
| proxy | `/api/platform/v1/health` | The proxy reaches platform |

### Logs

| Task | With the script | By hand: Compose | By hand: Kubernetes |
|---|---|---|---|
| One service | `./install.sh logs agents`: the last 200 lines, followed on a terminal | `$C logs -f agents` | `kubectl -n ops-ai logs deploy/agents -f` |
| Every service | `./install.sh logs` | `$C logs --since 1h` | `kubectl -n ops-ai logs deploy/<service> --since 1h` |
| The schema job | `./install.sh logs migrate` | `$C logs migrate` | `kubectl -n ops-ai logs job/migrate` |

Every service writes plain text lines to standard output, one event per line with `key=value` fields, for your log
collector to pick up. Structured JSON output is planned.

### Upgrade and roll back

```
./install.sh upgrade --version <new version>
```

At the same version it checks and changes nothing. Otherwise it backs up, gets the new images, applies the schema
(or, in DBA mode, writes the upgrade scripts to `./dba/` and waits for your DBA), restarts, checks, and on a failed
check restores the backup on the old version. In DBA mode it needs an admin login that may dump the database, as a
file: `--admin-url-file <file>`.

By hand, and on Kubernetes:

| Step | Who | What |
|---|---|---|
| 1 | DBA | Back up the database ([below](#back-up-and-restore)) |
| 2 | Operator | Get the new release's images |
| 3 | DBA | Apply the new release's database upgrade script as the schema owner, then its grants script. Each step checks the version it starts from and stops before any change when the database is somewhere else |
| 4 | Operator | Start the new images. Every service checks the database's schema version and refuses to start on one older than itself |

| Fact | Consequence |
|---|---|
| A service refuses a schema it does not know | An older release cannot start on a newer schema, so two releases cannot be mixed by mistake |
| Migrations do not roll back on their own | To go back, restore the backup from before the upgrade, or run the release's downgrade script where every step has one, and start the previous images |
| An index added to a very large table holds writes while it builds | The upgrade script names such indexes; on a table over about a million rows, build the index by hand first with `CREATE INDEX CONCURRENTLY` and the upgrade then finds it |
| A drift check compares a live database with what its release expects | It lists every missing, extra or changed object |
| Runs in flight keep their version | A waiting run resumes on the new release with the workflow or agent version it started on |
| The script has not yet upgraded across two releases that change the schema | The first release has no earlier one to upgrade from |

### Back up and restore

```
./install.sh backup
./install.sh restore backups/<file>.tar.gz
```

A backup is one `.tar.gz` in `./backups/`, readable only by its owner: a dump of the database, the files and
knowledge volumes, and `ops-ai.env`. A restore stops the services, recreates the database from the dump, puts the
volumes back, starts and checks; it refuses a backup made with another `OPS_SECRETS_KEY`. In DBA mode both need
`--admin-url-file <file>`, since a service's login cannot dump the database under its tenant policies.

> [!IMPORTANT]
> A backup holds `ops-ai.env` and its keys. Keep it as safe as the database: `OPS_SECRETS_KEY` unlocks every stored
> credential, and without it a restored installation cannot call your systems.

By hand, back up the database with your usual PostgreSQL tools, or on Azure with the automated backups and
point-in-time restore. Back up as the server admin: the tenant policies apply to the schema's owner too, so `pg_dump`
as the schema owner stops with a row-level security error.

```
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_dump -Fc -f /backup/ops.dump "host=<host> port=5432 user=<admin> dbname=ops sslmode=require"
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/out" alpine tar czf /out/files-data.tgz -C /data .
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/out" alpine tar czf /out/kb-data.tgz -C /data .
```

To restore by hand into a new database:

```
$C stop
psql -v ON_ERROR_STOP=1 "host=<host> port=5432 user=<admin> dbname=postgres sslmode=require" -c "CREATE DATABASE ops_restored OWNER ops_migrator"
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_restore --exit-on-error -d "host=<host> port=5432 user=<admin> dbname=ops_restored sslmode=require" /backup/ops.dump
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/files-data.tgz -C /data"
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/kb-data.tgz -C /data"
```

Then point each service's database setting at `ops_restored` and start everything again. On Kubernetes, back up the
files and kb volumes with your cluster's volume snapshots. When files are stored in S3 or Azure Blob, use that store's
own versioning or replication.

### Remove

`./install.sh uninstall` asks, then removes the containers, and asks again before deleting the volumes. It keeps
`ops-ai.env`.

### Scaling

| Part | How it scales | Status |
|---|---|---|
| Workflow runs | Add worker processes; each claims runs from the shared queue and runs 4 at once. A run waiting for a person holds no worker | Built |
| The APIs | Each service is stateless apart from files and kb, so more replicas can run behind the proxy or a Kubernetes Service | Built for every service except files and kb |
| files and kb | Their bytes are on a volume one replica can write, so they run one replica each | Partial |
| Crash recovery | A run's lease expires 15 seconds after its worker stops, and another worker continues it from its last saved step | Built |
| One tenant's load starving another's | Per-tenant caps on running runs | Planned |

### What to watch

| Signal | Why it matters | Healthy |
|---|---|---|
| The work queue | Rows waiting to be claimed mean the workers are busy or down | Claimed within a second or two |
| Crashed and recovered runs | Each crash re-runs a step and its model calls | Rare, each followed by a recovery |
| Tool calls left running | The gateway stopped mid-write, so the effect on your system is unknown | None; each one needs a person to check the system it called |
| Overdue tasks | People are not keeping up with the queue | Within the deadlines your workflows set |
| Model spend against budgets | A spent key stops new work | Below each key's cap |
| Database size and write load | Saved run state grows with open work | Steady; prune and vacuum on a schedule |
| Clock | Leases and timers use the database's clock; hosts must agree with it | Skew well under 15 seconds |

### Rotating keys

| Key | Steps |
|---|---|
| Approval key (`OPS_REVIEW_KEY`) | Set the new value for agents and tools and restart both. Approvals in flight must be given again |
| A service's signing key | Give the service a new key and key id, add its public key to every other service's trusted list beside the old one, restart the others, then the service; then remove the old key id and restart the others again |
| Sign-in token key (`OPS_PLATFORM_SIGNING_KEY`) | Set a new key and key id and restart every service; people may need to sign in again |
| Secrets key (`OPS_SECRETS_KEY`) | Changing it makes every stored credential unreadable, so each must be entered again. A rotation that re-encrypts them is planned |
| A provider's model key | The Security admin replaces it in the credential store; no restart |
| Database passwords | Change each login's password, update its setting, restart that service |
