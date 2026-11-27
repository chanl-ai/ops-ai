# Install and operate Ops AI

Status: current. How to install, run and maintain Ops AI on your own machines. The full client guide adds the architecture, data, security and deployment options.

<!-- Generated from docs/guide/install.md and docs/guide/operate.md by scripts/docs/build_guide.mjs; edit those, then run the build. The full guide is docs/deploy/client-install-guide.html. -->

## Install

<!-- The steps below are included from docs/deploy/install.md, the install script's guide, when the page and
INSTALL.md are built; edit them there. -->

Before you run the first command, you need six things ready: a machine, a DNS name, a database, a model, a first admin
and your sign-in details. This page lists what to have in hand, then points to the way that fits your setup. On
one machine, the install script does every step and checks the result. On a cluster, or when you run each step
yourself, the same images start from Compose or Kubernetes files. Version 1.2.0 is the current release, and its images
are published at `ghcr.io/chanl-ai/ops-ai`.

> [!NOTE]
> To try Ops AI on a laptop rather than install it for a team, use the [Quickstart](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/quickstart.md). It runs from a
> clone with a test model and a sample team.

### What to have ready

| Item | What you need | Details |
|---|---|---|
| A host | One Linux machine with Docker Engine 24 or newer, Docker Compose 2.22 or newer, `curl` and `tar`, 4 GB of memory for the containers and 15 GB of free disk | [Sizing](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/deployment-options.md#sizing) |
| A DNS name and TLS | A name such as `ops.example.com` on your load balancer or reverse proxy, forwarding to the port the script asks for | [The network](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/deployment-options.md#the-network) |
| PostgreSQL | For a trial, the script's built-in database. For real use, your own PostgreSQL 15 or newer with the `vector` extension: either a login that may change the schema, or DBA mode, where your DBA applies the scripts the install writes | [Data and database](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/data-and-database.md) |
| A model endpoint | Any OpenAI-compatible endpoint and its key. The built-in test model will do for a first look | [Models](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/models.md) |
| The first admin | A name and email address for the person who signs in first and invites everyone else | |
| Sign-in and outbound hosts | Your identity provider's OIDC or SAML details, and the hosts Ops AI will call, for the Security admin to set after the install | [Security and governance](https://github.com/chanl-ai/ops-ai/blob/main/docs/guide/security-and-governance.md) |

### Run the install script

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
| First admin's password, 12 characters or more | Generated and kept in `ops-ai.env` | `--admin-password-file <file>` (the answers key holds the password itself) | `ADMIN_PASSWORD` |
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
| `--offline <images.tar.gz>` | Loads the images from a [release package](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/release-package.md) instead of pulling them |

To run without questions, put the answers in a file, one `KEY=value` per line, and add `--yes`. A flag overrides the
same key in the file. Without a terminal the script behaves as if you had passed `--yes`.

```bash
./install.sh --answers install-answers.env --yes
```

For your own database, give a connection string such as `postgresql://ops_admin:<password>@db.example.com:5432/ops?sslmode=require`.
The script turns `sslmode=` into the form the services use.

### What the script does

<!-- site: steps -->
1. **Gets the images** for linux/amd64 or linux/arm64 from `ghcr.io/chanl-ai/ops-ai`. With `--offline`, it loads them
   from a release package's image file instead.
2. **Writes the settings file** `ops-ai.env`, readable only by its owner, and generates every key into it. The script
   prints no secret.
3. **Waits for your DBA** in `dba` mode. It writes the database scripts and each login's password to `./dba/`, prints
   three `psql` commands to run (its `1-server.sql` makes the roles and the database, then the bundle and the grants follow), and checks the schema before it goes on ([Database](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/database.md)).
4. **Starts everything** and waits for each health check. A model key you give is stored in Ops AI's credential
   store, and `ops-ai.env` does not hold it. An answers file holds `MODEL_API_KEY` in clear text, so delete that file after
   the install.
5. **Checks the install**: health through the published port, the sign-in page, a sign-in as the first admin, and one
   read from each service.

### What success looks like

The script ends by printing the address, the first admin's email and where the password is. With a public URL, the first
address is that URL and the second is the local one:

```text
Ops AI 1.2.0 is running.

  Open:      https://ops.example.com   (on this machine: http://localhost:8890)
  Sign in:   admin@example.com
  Password:  the one you gave, or the generated one: see OPS_BOOTSTRAP_ADMIN_PASSWORD in ops-ai.env
```

Open the address and sign in. Change the password, then delete the `OPS_BOOTSTRAP_ADMIN_PASSWORD` line from
`ops-ai.env`. Keep `ops-ai.env` with your backups, because its secrets key unlocks every stored credential.

You can run `./install.sh` again on a working install at any time. It checks the install and changes nothing, and it
leaves existing keys alone, because the secrets key in `ops-ai.env` unlocks every stored credential. If a check fails,
the script exits with an error and prints the failing line, and `./install.sh logs` shows what the containers reported.
The agents check cannot pass until a model is connected. The script connects one for you, so a failure there usually
points to the model endpoint or its key.

### The other commands

Run them from the folder the install ran in.

| Command | What it does |
|---|---|
| `./install.sh status` | Version, image source, database and model, each container's state, then the check |
| `./install.sh logs [service]` | The last 200 lines, followed on a terminal |
| `./install.sh backup [--out DIR]` | One archive of the database, the stored files and `ops-ai.env` ([Back up and restore](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/backup-and-restore.md)) |
| `./install.sh restore <file>` | Puts a backup back and checks ([Back up and restore](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/backup-and-restore.md)) |
| `./install.sh upgrade [--version V]` | Backs up, moves to version V, checks, and rolls back on a failed check ([Upgrade](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/upgrade.md)) |
| `./install.sh uninstall` | Asks, then removes the containers, and asks again before deleting the data. Keeps `ops-ai.env`. With `--yes`, add `--delete-data` to delete the data too |

In `dba` mode, the `backup`, `restore` and `upgrade` commands need a database admin login that is allowed to dump the
database, because the services' own logins cannot do so. Put a connection string such as
`postgresql://admin:password@host:5432/db` in a file and pass it with `--admin-url-file <file>`.

### Apply a changed setting

Running `./install.sh` again does not apply an edit to `ops-ai.env`, because it finds the install healthy and stops
after the check. To apply an edit, run Compose on the same files the script uses. The command below fits an install
with the built-in database and the test model. Leave out `-f deploy/compose/try.yaml` and both profiles when you use
your own database and a real model, and add `-f deploy/compose/dba.yaml` for `dba` mode.

```bash
docker compose -p ops-ai -f deploy/compose/app.yaml -f deploy/compose/try.yaml \
  --profile postgres --profile fake-model --env-file ops-ai.env up -d
```

Use the project name you chose, which `./install.sh status` prints.

### Turn on a feature flag

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

If `OPS_FLAGS` contains a name that Ops AI does not recognise, every service stops at start and lists the flags it
knows. A misspelt flag therefore shows up at once, instead of leaving you to think a feature is on when it is not.

### Set the embedding model

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
  only. Issue this one with `connect_model.py --key-id purpose:kb`, as in [Connect a model](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/compose.md#connect-a-model).
- Your PostgreSQL offers the `vector` extension (pgvector 0.5 or newer). The built-in database has it.

Until they are true, search runs on keywords alone and says so in each result. Changing either setting later embeds the
stored knowledge again, without reading any source again.

### Install from a company registry

When the machine reaches only your own registry, mirror the images there and point the script at it.

| Setting | What it moves | Default |
|---|---|---|
| `OPS_IMAGE_REGISTRY`, in the shell that runs the script | Where the Ops AI images are pulled from | `ghcr.io/chanl-ai/ops-ai` |
| `OPS_BASE_IMAGE_PREFIX`, in `ops-ai.env` | A registry prefix ending in `/` for third-party images such as the trial PostgreSQL | Docker Hub |

A machine with no registry at all uses `--offline` with a release package's image file.

### Limits

- Even with `--offline`, the script still pulls a few images from Docker Hub. It pulls `pgvector/pgvector:pg17` when you
  choose the built-in database. Backup and restore pull `alpine`, and against your own database they also pull
  `postgres:17-alpine`. None of these pulls follow `OPS_IMAGE_REGISTRY` or `OPS_BASE_IMAGE_PREFIX`, so on a machine that
  cannot reach Docker Hub you cannot back up through the script.
- `--build` builds every image except the one that runs code tools. Start such an install with images from a registry or
  a release package until that is fixed.
- The script upgrades one install at a time and does not manage a standby. A second machine with the same install is a
  standby you restore a backup onto ([Back up and restore](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/backup-and-restore.md)).

### Other ways to install

| Way | Use it when |
|---|---|
| [Docker Compose by hand](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/compose.md) | You run each step yourself on one machine. The DBA's scripts are in [Database](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/database.md) |
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
  only the new release after it. Agents 0120 (stored skill step tools) does not need the stop: it rewrites skill and
  agent versions one batch per transaction, each batch setting its table's policy aside and putting it back, so the
  services keep serving. A version the earlier release saves after its last pass is refused by the publish check and
  the attach until its builder marks the step's tool.

### Roll back

Migrations do not roll back on their own. Either restore the backup taken before the upgrade, or have your DBA run the
release's `downgrade.sql` where every step has one; then start the previous images. The script does this for you when
its check fails.

### Back up and restore with the script

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

### Back up and restore by hand

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
