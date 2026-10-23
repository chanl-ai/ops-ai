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

## Appendix: by hand

Every step `install.sh` runs can be done by hand: the stack, its settings, keys, model connection, upgrade, backup and
logs in `compose.md`; the DBA's scripts, logins, upgrades and drift check in `database.md`; the same images on
Kubernetes in `kubernetes.md`.
