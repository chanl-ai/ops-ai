# Install with the script

Status: current.

Installing Ops AI by hand means generating a dozen keys, writing a settings file, applying a database schema, starting
a dozen containers in the right order and then finding out whether any of it works. A mistake in the middle leaves an
install that looks started and cannot sign anyone in. The install script does those steps in order, checks the result,
and afterwards upgrades, backs up, restores and reports on the same install. Use it when Ops AI runs on one Linux
machine with Docker. For a cluster, use [Kubernetes](kubernetes.md). To run every step yourself, use
[Docker Compose](compose.md).

The release's own checks run the script on an Ubuntu 24.04 runner: a fresh install, a second run that changes nothing,
an upgrade to the same version, a backup, a restore and the mode where your DBA applies the schema. It has also run on
Docker Desktop for macOS. It has not yet been run on a client's own server.

## What you need before you start

| Item | What you need |
|---|---|
| The machine | Linux with Docker Engine 24 or newer, Docker Compose 2.22 or newer, `curl` and `tar`. Python is not needed. At least 4 GB of memory for the containers and 15 GB of free disk where Docker keeps its images ([Sizing](../guide/deployment-options.md#sizing)) |
| A free port | 8890 by default. Your TLS terminator or load balancer forwards to it |
| A database | For a trial, the script starts one for you. For real use, your own PostgreSQL 15 or newer with the `vector` extension available, and either a login that may change the schema or a DBA who applies the scripts the install writes ([Database](database.md)) |
| A model | An OpenAI-compatible endpoint, its model name and its key. For a first look, the script's built-in test model needs none of these |
| The first admin | A name, an email address and a password of at least 12 characters (the script generates one when you give none) |

The script checks the machine before it changes anything. It names each missing item, such as an old Docker version or a
busy port, and stops.

## Run the install script

Clone the release you want and run the script from the clone. The script installs the version of the tag you cloned.
On a clone without a release tag it falls back to the version in the repository's version file, which can be older
than the code you cloned.

```bash
git clone --branch v1.2.0 https://github.com/chanl-ai/ops-ai.git
cd ops-ai
./install.sh
```

The script asks the questions below. Each has a default, a flag and a key for an answers file.

| Question | Default | Flag | Answers key |
|---|---|---|---|
| Port on this machine | 8890 | `--port` | `PORT` |
| Public URL | `http://localhost:<port>` | `--public-url` | `PUBLIC_URL` |
| Compose project name | `ops-ai` | `--project` | `PROJECT` |
| Organisation name | My organisation | `--org` | `ORG_NAME` |
| First admin's email and name | `admin@example.com`, First Admin | `--admin-email`, `--admin-name` | `ADMIN_EMAIL`, `ADMIN_NAME` |
| First admin's password, 12 characters or more | Generated and kept in `ops-ai.env` | `--admin-password-file` | `ADMIN_PASSWORD` |
| Database | `builtin`: a PostgreSQL 17 container, for a trial | `--database builtin` or `--database postgresql://user:pass@host:5432/db` | `DATABASE` |
| Who applies the schema (your own PostgreSQL only) | `auto`: the install applies it with the login you gave | `--db-mode auto` or `--db-mode dba` | `DB_MODE` |
| Model | `test`: the built-in test model, which calls no provider | `--model <OpenAI-compatible base URL>/v1` with `--model-name` and `--model-key-file` | `MODEL`, `MODEL_NAME`, `MODEL_API_KEY` |
| Image version | The tag you cloned | `--version` | `VERSION` |

A few more flags change how the script behaves.

| Flag | What it does |
|---|---|
| `--model-input-price`, `--model-output-price` | The price per million tokens, which the cost log uses. Both default to 0 |
| `--model-budget` | The spending cap on each model key. Default 100 |
| `--dba-timeout <seconds>` | How long an unattended run waits for your DBA. Default 3600 |
| `--env-file <file>` | Where the settings file lives. Default `./ops-ai.env` |
| `--build` | Builds the images from the clone instead of pulling them. The clone must be a git checkout |
| `--offline <images.tar.gz>` | Loads the images from a [release package](release-package.md) instead of pulling them |

To run without questions, put the answers in a file, one `KEY=value` per line, and add `--yes`. A flag overrides the
same key in the file. Without a terminal the script behaves as if you had passed `--yes`.

```bash
./install.sh --answers install-answers.env --yes
```

For your own database, give a connection string such as `postgresql://ops_admin:<password>@db.example.com:5432/ops?sslmode=require`.
The script turns `sslmode=` into the form the services use.

## What the script does

<!-- site: steps -->
1. **Gets the images** for linux/amd64 or linux/arm64 from `ghcr.io/chanl-ai/ops-ai`. With `--offline`, it loads them
   from a release package's image file instead.
2. **Writes the settings file** `ops-ai.env`, readable only by its owner, and generates every key into it. The script
   prints no secret.
3. **Waits for your DBA** in `dba` mode. It writes the database scripts and each login's password to `./dba/`, prints
   the three `psql` commands to run, and checks the schema before it goes on ([Database](database.md)).
4. **Starts everything** and waits for each health check. A model key you give is stored in Ops AI's credential
   store, and `ops-ai.env` never holds it.
5. **Checks the install**: health through the published port, the sign-in page, a sign-in as the first admin, and one
   read from each service.

## What success looks like

The script ends by printing the address, the first admin's email and where the password is:

```text
Ops AI 1.2.0 is running.

  Open:      http://localhost:8890   (on this machine: http://localhost:8890)
  Sign in:   admin@example.com
  Password:  the one you gave, or the generated one: see OPS_BOOTSTRAP_ADMIN_PASSWORD in ops-ai.env
```

Open the address and sign in. Change the password, then delete the `OPS_BOOTSTRAP_ADMIN_PASSWORD` line from
`ops-ai.env`. Keep `ops-ai.env` with your backups, because its secrets key unlocks every stored credential.

Running `./install.sh` again on a working install checks it and changes nothing. The script never replaces existing keys.

If a check fails, the script exits with an error and the failing line. `./install.sh logs` shows what the containers
said. The agents check fails until a model is connected, which the script does for you, so a failure there usually
means the model endpoint or its key.

## The other commands

Run them from the folder the install ran in.

| Command | What it does |
|---|---|
| `./install.sh status` | Version, image source, database and model, each container's state, then the check |
| `./install.sh logs [service]` | The last 200 lines, followed on a terminal |
| `./install.sh backup [--out DIR]` | One archive of the database, the stored files and `ops-ai.env` ([Back up and restore](backup-and-restore.md)) |
| `./install.sh restore <file>` | Puts a backup back and checks ([Back up and restore](backup-and-restore.md)) |
| `./install.sh upgrade [--version V]` | Backs up, moves to version V, checks, and rolls back on a failed check ([Upgrade](upgrade.md)) |
| `./install.sh uninstall` | Asks, then removes the containers, and asks again before deleting the data. Keeps `ops-ai.env`. With `--yes`, add `--delete-data` to delete the data too |

In `dba` mode, `backup`, `restore` and `upgrade` need a database admin login that may dump the database, in a file:
`--admin-url-file <file>` holding `postgresql://admin:password@host:5432/db`. The services' own logins cannot dump it.

## Apply a changed setting

Running `./install.sh` again does not apply an edit to `ops-ai.env`, because it finds the install healthy and stops
after the check. To apply an edit, run Compose on the same files the script uses. The command below fits an install
with the built-in database and the test model. Leave out `-f deploy/compose/try.yaml` and both profiles when you use
your own database and a real model, and add `-f deploy/compose/dba.yaml` for `dba` mode.

```bash
docker compose -p ops-ai -f deploy/compose/app.yaml -f deploy/compose/try.yaml \
  --profile postgres --profile fake-model --env-file ops-ai.env up -d
```

Use the project name you chose, which `./install.sh status` prints.

## Turn on a feature flag

A feature that is not yet released to every install ships behind a flag and is off. To turn one on, list it in
`ops-ai.env` and [apply the setting](#apply-a-changed-setting).

```bash
OPS_FLAGS=mcp_gateway,tool_search
```

| Flag | Turns on |
|---|---|
| `mcp_gateway` | The MCP address that outside assistants (Claude, Cursor, Copilot) use to reach a team's tools, and the console's MCP channel |
| `tool_search` | Agents with many tools search for the one they need |
| `plugin_updates` | Each team keeps the plugin version it took and reviews an upgrade before its tools change |
| `area_tabs` | The console shows one area at a time, picked from the top bar |

A name Ops AI does not know stops every service at start and lists the known flags, so a typo cannot pass for a flag
that is off.

## Set the embedding model

Knowledge search by meaning needs one embedding model for the whole install. Two settings in `ops-ai.env` name it.

| Setting | Default | What it does |
|---|---|---|
| `OPS_EMBEDDING_ALIAS` | `bank-embed` | The model alias of kind embedding that knowledge is embedded with |
| `OPS_EMBEDDING_WIDTH` | `1536` | The vector width. Above 1,998 every service refuses to start, because no vector index holds more |

Three things must be true before search by meaning works.

- An alias of kind embedding exists under that name and points at your provider's embedding model. The script's connect
  step, and the console's **Aliases** page, create chat aliases only. An embedding alias is created through the models
  service's API with `"kind": "embedding"`.
- The knowledge service has its own model key, `OPS_MODELS_KEY_KB`. The script issues keys for agents and documents
  only. Issue this one with `connect_model.py --key-id purpose:kb`, as in [Connect a model](compose.md#connect-a-model).
- Your PostgreSQL offers the `vector` extension (pgvector 0.5 or newer). The built-in database has it.

Until they are true, search runs on keywords alone and says so in each result. Changing either setting later embeds the
stored knowledge again, without reading any source again.

## Install from a company registry

When the machine reaches only your own registry, mirror the images there and point the script at it.

| Setting | What it moves | Default |
|---|---|---|
| `OPS_IMAGE_REGISTRY`, in the shell that runs the script | Where the Ops AI images are pulled from | `ghcr.io/chanl-ai/ops-ai` |
| `OPS_BASE_IMAGE_PREFIX`, in `ops-ai.env` | A registry prefix ending in `/` for third-party images such as the trial PostgreSQL | Docker Hub |

A machine with no registry at all uses `--offline` with a release package's image file.

## Limits

- With `--offline`, the script still pulls `pgvector/pgvector:pg17` when you choose the built-in database. Backup and
  restore pull `alpine`, and backup and restore against your own database pull `postgres:17-alpine`, from Docker Hub.
  None of these follow `OPS_IMAGE_REGISTRY` or `OPS_BASE_IMAGE_PREFIX`, so a machine with no Docker Hub access cannot back
  up through the script.
- `--build` builds every image except the one that runs code tools. Start such an install with images from a registry or
  a release package until that is fixed.
- The script upgrades one install at a time and does not manage a standby. A second machine with the same install is a
  standby you restore a backup onto ([Back up and restore](backup-and-restore.md)).

## Doing each step yourself

Every step the script runs can be done by hand. The containers and settings are in [Docker Compose](compose.md), the
DBA's scripts in [Database](database.md), and a cluster in [Kubernetes](kubernetes.md).
