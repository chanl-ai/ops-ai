# Install Ops AI with install.sh

Status: current. Proven on one machine (macOS, Docker Desktop, linux/arm64 images); not yet run on a client's Linux
server.

<!-- Built by c-426; the proof is deploy/release/install_proof.sh, with evidence in the card's evidence folder. -->

The install script installs Ops AI on one machine with Docker from a clone of this repository, asks a few questions,
checks the result, and then upgrades, backs up, restores and reports on the same install. The steps it runs can also be
done by hand (appendix below).

## Install

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
   waiting for every health check. A provider key is stored in Secrets through the API as `MODEL_PROVIDER_KEY`,
   never in `ops-ai.env`; models-service reads it by that name.
5. Runs the check: health through the published port, the console's sign-in page, a sign-in as the first admin, one
   read from every service through the proxy, and agents' health (a model is connected). Then it prints the URL and
   how to sign in.

Running `./install.sh` again on a working install checks it, says "nothing changed" and changes nothing. On an install
that is not running, it reuses `ops-ai.env` and its keys and starts it. It never makes new keys over existing ones:
`OPS_SECRETS_KEY` unlocks the stored credentials.

## The other commands

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

## What is proven and what is not

| Claim | Evidence |
|---|---|
| Clone to signed in, images pulled from GHCR | `install_proof.sh` steps 1 to 3, run with `SIGNED_IN=1` (a registry login) while the packages are internal; the anonymous run waits for them to be public (**unverified**) |
| Every console page loads | `docs/usecases/lib/stg_click_walk.mjs`, steps 4 and 7 |
| A rerun and a same-version upgrade change nothing | steps 5 and 6: `ops-ai.env` checksum and container ids unchanged |
| Backup and restore | step 7: a table and a file made after the backup are gone after the restore |
| A failed upgrade rolls back | step 8b: a release whose console exits; exit 1, back on the old version, status passes |
| DBA mode, provider key through Secrets | step 9: PostgreSQL 17 with TLS and an admin that is not a superuser; the three printed commands; backup and restore with `--admin-url-file` |
| An upgrade across two releases that changes the schema | **unverified**: 0.1.0 is the first release. The auto path is the migrate job `compose.md` already proves; the DBA path renders Alembic's offline SQL from the recorded revisions (`deploy/install/install_api.py`) |
| A Linux server | **unverified**: the proof ran on Docker Desktop for macOS |

Images and the version: `deploy/release/version` names the version a checkout installs. A version tag `v<version>`
runs `.github/workflows/release-images.yml`, which builds every image for both platforms with
`deploy/release/images.sh` and pushes `<version>` and `latest`. The same script builds the release package's images
(`release-package.md`) and `--build`.

## Behind a company mirror

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

### Developer workspaces

The devcontainer (`.devcontainer/`) and the shared-host template (`deploy/devhost/`) take the same settings. In a
devcontainer, set them in the shell that opens it or in `.devcontainer/.env.local`; the compose file passes them to the
image build and to the workspace, where `make install` reads the mirror whenever `UV_DEFAULT_INDEX` is set. On the shared
host, push the template with `--variable 'mirror_settings={...}'` and `--variable base_image_prefix=...`
(`deploy/devhost/README.md`). Node comes from the Node image, not from nodejs.org, and the devcontainer's Node feature
(a download from GitHub's registry) is gone.

### Installing the locked versions through the mirror

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

## Appendix: by hand

Every step `install.sh` runs can be done by hand: the stack, its settings, keys, model connection, upgrade, backup and
logs in `compose.md`; the DBA's scripts, logins, upgrades and drift check in `database.md`; the same images on
Kubernetes in `kubernetes.md`.
