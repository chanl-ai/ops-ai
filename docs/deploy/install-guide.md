# Install and operate Ops AI

Status: current. How to install, run and maintain Ops AI on your own machines. The full client guide adds the architecture, data, security and deployment options.

<!-- Generated from docs/guide/install.md and docs/guide/operate.md by scripts/docs/build_guide.mjs; edit those, then run the build. The full guide is docs/deploy/client-install-guide.html. -->

## Install

<!-- The steps below are included from docs/deploy/install.md, the install script's guide, when the page and
INSTALL.md are built; edit them there. -->

Install Ops AI for a team on your own infrastructure. On one machine, the install script does every step and checks the
result; on a cluster, or when you run each step yourself, the same images start from Compose or Kubernetes files.
Version 1.0.0 is the current release, and its images are published at `ghcr.io/chanl-ai/ops-ai`.

> [!NOTE]
> To try Ops AI on a laptop rather than install it for a team, use the [Quickstart](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/quickstart.md): it runs from a
> clone with a test model and a sample team.

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

### What it does

<!-- site: steps -->
1. **Gets the images** for linux/amd64 or linux/arm64 from `ghcr.io/chanl-ai/ops-ai`. `--offline <images.tar.gz>`
   loads them from a [release package](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/release-package.md) instead, for a machine with no registry access.
2. **Writes the settings file** `ops-ai.env`, readable only by its owner, and generates every key into it. No secret is
   printed.
3. **Waits for your DBA** in `dba` mode: it writes the database scripts and each login's password to `./dba/`, prints
   the three `psql` commands to run, and checks the schema before it goes on ([Database](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/database.md)).
4. **Starts everything** and waits for each health check. A model key you give is stored in Ops AI's credential
   store, never in `ops-ai.env`.
5. **Checks the install**: health through the published port, the sign-in page, a sign-in as the first admin, and one
   read from every service.

Running `./install.sh` again on a working install checks it and changes nothing. It never replaces existing keys,
because the secrets key in `ops-ai.env` unlocks every stored credential.

### The other commands

Run them from the folder the install ran in.

| Command | What it does |
|---|---|
| `./install.sh status` | Version, image source, database and model, each container's state, then the check |
| `./install.sh logs [service]` | The last 200 lines, followed on a terminal |
| `./install.sh backup [--out DIR]` | One archive of the database, the stored files and `ops-ai.env` ([Back up and restore](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/backup-and-restore.md)) |
| `./install.sh restore <file>` | Puts a backup back and checks ([Back up and restore](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/backup-and-restore.md)) |
| `./install.sh upgrade [--version V]` | Backs up, moves to version V, checks, and rolls back on a failed check ([Upgrade](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/upgrade.md)) |
| `./install.sh uninstall` | Asks, then removes the containers; asks again before deleting the data. Keeps `ops-ai.env` |

In `dba` mode, `backup`, `restore` and `upgrade` need a database admin login that may dump the database, in a file:
`--admin-url-file <file>` holding `postgresql://admin:password@host:5432/db`. The services' own logins cannot dump it.

### Turn on a feature flag

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

### Set the embedding model

Knowledge search by meaning uses one embedding model per install, set in `ops-ai.env`.

| Setting | Default | What it does |
|---|---|---|
| `OPS_EMBEDDING_ALIAS` | `bank-embed` | The model alias of kind embedding; bind it to your provider's embedding model the way [Connect a model](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/compose.md#connect-a-model) binds a chat model |
| `OPS_EMBEDDING_WIDTH` | `1536` | The vector width. Above 1,998 every service refuses to start, since no vector index holds it |

Changing either one embeds the stored knowledge again; no source is read again. Without an embedding model, search runs
on keywords alone and says so in each result. Your own PostgreSQL needs the `vector` extension (pgvector 0.5 or newer)
offered; the built-in database has it.

### Install from a company registry

When the machine reaches only your own registry, mirror the images there and point the script at it:

| Setting | What it moves | Default |
|---|---|---|
| `OPS_IMAGE_REGISTRY` | Where the Ops AI images are pulled from | `ghcr.io/chanl-ai/ops-ai` |
| `OPS_BASE_IMAGE_PREFIX` | A registry prefix ending in `/` for third-party images, such as PostgreSQL and the policy engine | Docker Hub |

A machine with no registry at all uses `--offline` with a release package's image file.

### Limits

- Proven on Docker Desktop for macOS; a run on a Linux server is not yet recorded.
- An upgrade across two releases that change the schema has not run yet: 1.0.0 is the first release.

### Other ways to install

| Way | Use it when |
|---|---|
| [Docker Compose by hand](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/compose.md) | You run each step yourself on one machine |
| [Kubernetes](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/kubernetes.md) | Your platform team runs a cluster |
| [Release package](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/release-package.md) | The machines have no internet access |

### The command line on its own

To script Ops AI from a machine that does not run it, install only the `opsai` command, including behind a company
package mirror or with no network: [Install the command line](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/install-cli.md).

## Operate

Keep an install healthy once it runs: check it and read its logs, move it to a new release, back it up, and rotate its
keys. The install script's commands come first on each page; the Compose and Kubernetes commands follow for installs
made by hand.

### Check the install

```bash
./install.sh status
```

It prints the version, image source, database and model, each container's state, then runs the install check: health
through the published port, the sign-in page, a sign-in as the first admin, and one read from every service.

| Check | Compose | Kubernetes | Healthy |
|---|---|---|---|
| Every container | `$C ps` | `kubectl -n ops-ai get pods` | Each service healthy or ready; the schema job exited 0 |
| The entry point | `curl -fsS https://<your host>/api/platform/v1/health` | Same | `{"status":"ok"}` |
| Sign-in | Open your address and sign in | Same | The console opens |

Here `$C` is your Compose command, for example `docker compose -p ops-ai -f deploy/compose/app.yaml --env-file
ops-ai.env`.

| Container | Unhealthy means |
|---|---|
| agents | The database is unreachable, or no model is connected: it answers 503 until one is |
| tools | The policy engine does not serve the gateway's own policy: it answers 503 `policy_drift` |
| worker | The database is unreachable |
| any other service | The process is down |
| proxy | It cannot reach the platform service |

### Read the logs

| Task | Script | Compose | Kubernetes |
|---|---|---|---|
| One service | `./install.sh logs agents` | `$C logs -f agents` | `kubectl -n ops-ai logs deploy/agents -f` |
| Every service | `./install.sh logs` | `$C logs --since 1h` | `kubectl -n ops-ai logs deploy/<service> --since 1h` |
| The schema job | `./install.sh logs migrate` | `$C logs migrate` | `kubectl -n ops-ai logs job/migrate` |

Each line is one JSON object with the time, level, event, service, and the request, tenant and team ids. Secret values
are masked before the line is written.

### What to watch

| Signal | Why it matters | Healthy |
|---|---|---|
| The work queue | Runs waiting to be claimed mean the workers are busy or down | Claimed within a second or two |
| Crashed and recovered runs | Each crash runs a step and its model calls again | Rare, each followed by a recovery |
| Tool calls left running | The gateway stopped mid-write, so the effect on your system is unknown | None; each needs a person to check the system it called |
| Overdue human tasks | People are not keeping up with the queue | Within the deadlines your workflows set |
| Model spend against budgets | A spent key stops new work | Below each key's cap |
| Database size and write load | Saved run state grows with open work | Steady; vacuum on a schedule |
| Clock | Leases and timers use the database's clock | Hosts within a few seconds of it |

### Scale

| Part | How it scales |
|---|---|
| Workflow runs | Add worker processes. Each runs 4 runs at once from the shared queue; a run waiting for a person holds no worker |
| The APIs | Every service except files and knowledge is stateless, so more replicas can run behind the proxy or a Service |
| Files and knowledge | One replica each, since their bytes are on a volume one replica writes |
| Crash recovery | A run's lease expires 15 seconds after its worker stops, and another worker continues from its last saved step |

### Upgrade with the script

```bash
git fetch --tags && git checkout v<new version>
./install.sh upgrade
```

The script backs up, gets the new images, applies the schema, restarts, and checks. If the check fails, it restores the
backup on the old version and exits with an error. At the version already running, it checks and changes nothing.
`--version V` picks a version other than the checkout's.

In `dba` mode it writes the upgrade scripts to `./dba/upgrade-<from>-to-<to>/`, waits for your DBA to apply them, and
needs `--admin-url-file <file>` to take the backup.

### Upgrade by hand

<!-- site: steps -->
1. **Back up** the database and the stored files ([Back up and restore](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/backup-and-restore.md)).
2. **Upgrade the database.** Your DBA applies the new release's `upgrade-roles.sql`, then `upgrade.sql` as the schema
   owner, then the new release's `grants.sql` ([Database](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/database.md#upgrade)).
3. **Start the new images.**

| Install | Command |
|---|---|
| Compose | Set `OPS_IMAGE_TAG` to the new version, then `docker compose -p ops-ai -f deploy/compose/app.yaml --env-file ops-ai.env up -d` (add `-f deploy/compose/dba.yaml` in DBA mode). Without a DBA, the schema job applies the upgrade before the services start |
| Kubernetes | Set the new tag in the overlay, then `kubectl -n ops-ai delete job migrate` and `kubectl apply -k <overlay>`, since a finished Job cannot change |

### How it behaves

- Every service checks the database's schema version at start and refuses one it does not match, naming the upgrade
  that is missing. Two releases cannot be mixed by mistake.
- Each step of `upgrade.sql` checks the version it starts from and stops before any change when the database is
  somewhere else, so running it twice is refused.
- Some steps move rows that the running release still writes. Stop the services before the database step, and start
  only the new release after it.

### Roll back

Migrations do not roll back on their own. Either restore the backup taken before the upgrade, or have your DBA run the
release's `downgrade.sql` where every step has one; then start the previous images. The script does this for you when
its check fails.

### With the script

```bash
./install.sh backup
./install.sh restore backups/<file>.tar.gz
```

A backup is one archive in `./backups/`, readable only by its owner, holding a dump of the database, the files and
knowledge volumes, and `ops-ai.env`. `--out DIR` writes it elsewhere. A restore stops the services, recreates the
database from the dump, puts the volumes back, starts everything and runs the install check. It refuses a backup made
with another secrets key.

In `dba` mode both commands need `--admin-url-file <file>`: the services' own logins cannot dump the database under
its tenant policies.

> [!IMPORTANT]
> A backup holds `ops-ai.env` and its keys. Keep it as safe as the database: `OPS_SECRETS_KEY` unlocks every stored
> credential, and without it a restored install cannot call your systems.

### By hand

Back up the database as the server admin, with your usual PostgreSQL tools or, on Azure, automated backups and
point-in-time restore. A dump as the schema owner stops with a row-level security error, because the tenant policies
apply to the owner too.

```bash
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_dump -Fc -f /backup/ops.dump "host=<host> port=5432 user=<admin> dbname=ops sslmode=require"
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/out" alpine tar czf /out/files-data.tgz -C /data .
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/out" alpine tar czf /out/kb-data.tgz -C /data .
```

Keep a copy of the settings file, or at least `OPS_SECRETS_KEY`, with each backup.

To restore into a new database, stop the services, then:

```bash
psql -v ON_ERROR_STOP=1 "host=<host> port=5432 user=<admin> dbname=postgres sslmode=require" \
  -c "CREATE DATABASE ops_restored OWNER ops_migrator"
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_restore --exit-on-error -d "host=<host> port=5432 user=<admin> dbname=ops_restored sslmode=require" /backup/ops.dump
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/files-data.tgz -C /data"
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/kb-data.tgz -C /data"
```

Point each service's database setting at `ops_restored`, keep the same keys in the settings file, and start
everything again.

### What to back up where

| Install | Database | Files and knowledge bytes |
|---|---|---|
| Script or Compose | `pg_dump` as the server admin | The `files-data` and `kb-data` volumes |
| Kubernetes | `pg_dump` as the server admin | Volume snapshots of the files and kb claims |
| Files in S3 or Azure Blob | As above | The store's own versioning or replication |

### Rotate keys

| Key | Steps |
|---|---|
| Approval key (`OPS_REVIEW_KEY`) | Set the new value for agents and tools and restart both. Approvals in flight must be given again |
| A service's signing key | Give the service a new key and key id, add its public key to every other service's trusted list beside the old one, restart the others, then the service; then remove the old key id and restart the others again |
| Sign-in token key (`OPS_PLATFORM_SIGNING_KEY`) | Set a new key and key id and restart every service; people may need to sign in again |
| Secrets key (`OPS_SECRETS_KEY`) | Changing it makes every stored credential unreadable, so each must be entered again. A rotation that re-encrypts them is planned |
| A provider's model key | A Security admin replaces it in the credential store; no restart |
| Database passwords | Change each login's password, update its setting, restart that service |

### Remove

`./install.sh uninstall` asks, then removes the containers, and asks again before deleting the data. It keeps
`ops-ai.env`. By hand: `docker compose ... down` keeps the volumes and `down -v` deletes them; on Kubernetes,
`kubectl delete -k <overlay>` removes the volume claims with it.

### Limits

- An upgrade across two releases that change the schema has not run yet: 1.0.0 is the first release.
- Metrics are planned; health checks and logs are built.
- Ops AI schedules no backups; run the backup from your scheduler or use your database's own.
