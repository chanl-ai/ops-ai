# Install with the script

Status: current. Proven end to end on one machine with Docker Desktop; not yet run on a client's Linux server.

One script installs Ops AI on a Linux machine with Docker, checks that it works, and later upgrades, backs up, restores
and reports on the same install. Use it when Ops AI runs on one machine. For a cluster, use
[Kubernetes](kubernetes.md); to run every step yourself, use [Docker Compose](compose.md).

## Install

```bash
git clone --branch v1.0.0 https://github.com/chanl-ai/ops-ai.git
cd ops-ai
./install.sh
```

The script installs the version of the tag you cloned. The machine needs Docker Engine 24 or newer, Docker Compose
2.22 or newer, curl, tar, 4 GB of memory for the containers and 15 GB of free disk; Python is not needed. A preflight
names anything missing and stops before it changes anything.

It asks these questions. Each has a default, a flag, and a key for an answers file.

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

To run it unattended, put the answers in a file, one `KEY=value` per line, and add `--yes`. Flags win over the file.

```bash
./install.sh --answers install-answers.env --yes
```

When it finishes it prints the address and how to sign in as the first admin.

## What it does

<!-- site: steps -->
1. **Gets the images** for linux/amd64 or linux/arm64 from `ghcr.io/chanl-ai/ops-ai`. `--offline <images.tar.gz>`
   loads them from a [release package](release-package.md) instead, for a machine with no registry access.
2. **Writes the settings file** `ops-ai.env`, readable only by its owner, and generates every key into it. No secret is
   printed.
3. **Waits for your DBA** in `dba` mode: it writes the database scripts and each login's password to `./dba/`, prints
   the three `psql` commands to run, and checks the schema before it goes on ([Database](database.md)).
4. **Starts everything** and waits for each health check. A model key you give is stored in Ops AI's credential
   store, never in `ops-ai.env`.
5. **Checks the install**: health through the published port, the sign-in page, a sign-in as the first admin, and one
   read from every service.

Running `./install.sh` again on a working install checks it and changes nothing. It never replaces existing keys,
because the secrets key in `ops-ai.env` unlocks every stored credential.

## The other commands

Run them from the folder the install ran in.

| Command | What it does |
|---|---|
| `./install.sh status` | Version, image source, database and model, each container's state, then the check |
| `./install.sh logs [service]` | The last 200 lines, followed on a terminal |
| `./install.sh backup [--out DIR]` | One archive of the database, the stored files and `ops-ai.env` ([Back up and restore](backup-and-restore.md)) |
| `./install.sh restore <file>` | Puts a backup back and checks ([Back up and restore](backup-and-restore.md)) |
| `./install.sh upgrade [--version V]` | Backs up, moves to version V, checks, and rolls back on a failed check ([Upgrade](upgrade.md)) |
| `./install.sh uninstall` | Asks, then removes the containers; asks again before deleting the data. Keeps `ops-ai.env` |

In `dba` mode, `backup`, `restore` and `upgrade` need a database admin login that may dump the database, in a file:
`--admin-url-file <file>` holding `postgresql://admin:password@host:5432/db`. The services' own logins cannot dump it.

## Turn on a feature flag

A feature that is not yet released to every install ships behind a flag and is off. To turn one on, list it in
`ops-ai.env` and run `./install.sh` again to apply the change.

```bash
OPS_FLAGS=mcp_gateway,tool_search
```

| Flag | Turns on |
|---|---|
| `mcp_gateway` | The MCP address outside assistants (Claude, Cursor, Copilot) use to reach a team's tools, and the console's MCP channel |
| `tool_search` | Agents with many tools search for the one they need |
| `plugin_updates` | Each team keeps the plugin version it took and reviews an upgrade before its tools change |
| `area_tabs` | The console shows one area at a time, picked from the top bar |

A name Ops AI does not know stops every service at start with the list of known flags, so a typo never reads as off.

## Set the embedding model

Knowledge search by meaning uses one embedding model per install, set in `ops-ai.env`.

| Setting | Default | What it does |
|---|---|---|
| `OPS_EMBEDDING_ALIAS` | `bank-embed` | The model alias of kind embedding; bind it to your provider's embedding model the way [Connect a model](compose.md#connect-a-model) binds a chat model |
| `OPS_EMBEDDING_WIDTH` | `1536` | The vector width. Above 1,998 every service refuses to start, since no vector index holds it |

Changing either one embeds the stored knowledge again; no source is read again. Without an embedding model, search runs
on keywords alone and says so in each result. Your own PostgreSQL needs the `vector` extension (pgvector 0.5 or newer)
offered; the built-in database has it.

## Install from a company registry

When the machine reaches only your own registry, mirror the images there and point the script at it:

| Setting | What it moves | Default |
|---|---|---|
| `OPS_IMAGE_REGISTRY`, in the shell that runs the script | Where the Ops AI images are pulled from | `ghcr.io/chanl-ai/ops-ai` |
| `OPS_BASE_IMAGE_PREFIX`, in `ops-ai.env` | A registry prefix ending in `/` for third-party images, such as PostgreSQL and the policy engine | Docker Hub |

A machine with no registry at all uses `--offline` with a release package's image file.

## Limits

- Proven on Docker Desktop for macOS; a run on a Linux server is not yet recorded.
- An upgrade across two releases that change the schema has not run yet: 1.0.0 is the first release.

## Appendix: by hand

Every step the script runs can be done by hand: the containers and settings in [Docker Compose](compose.md), the DBA's
scripts in [Database](database.md), and a cluster in [Kubernetes](kubernetes.md).
