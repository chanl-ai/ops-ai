# Operate

Status: current.

How to check, upgrade, back up, restore and scale an Ops AI install. The install script's commands come first; the
manual commands after them are the fallback, and the ones Kubernetes uses.

Run the script's commands from the clone the install ran in; they read its settings from `ops-ai.env` there. In the
manual commands, `$C` is the Compose command for your install, for example
`docker compose -p ops-ai -f deploy/compose/app.yaml -f deploy/compose/dba.yaml --env-file ops-ai.env`, and `ops-ai`
is the Kubernetes namespace.

## Status and health

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

## Logs

| Task | With the script | By hand: Compose | By hand: Kubernetes |
|---|---|---|---|
| One service | `./install.sh logs agents`: the last 200 lines, followed on a terminal | `$C logs -f agents` | `kubectl -n ops-ai logs deploy/agents -f` |
| Every service | `./install.sh logs` | `$C logs --since 1h` | `kubectl -n ops-ai logs deploy/<service> --since 1h` |
| The schema job | `./install.sh logs migrate` | `$C logs migrate` | `kubectl -n ops-ai logs job/migrate` |

Every service writes plain text lines to standard output, one event per line with `key=value` fields, for your log
collector to pick up. Structured JSON output is planned.

## Upgrade and roll back

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

## Back up and restore

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

## Remove

`./install.sh uninstall` asks, then removes the containers, and asks again before deleting the volumes. It keeps
`ops-ai.env`.

## Scaling

| Part | How it scales | Status |
|---|---|---|
| Workflow runs | Add worker processes; each claims runs from the shared queue and runs 4 at once. A run waiting for a person holds no worker | Built |
| The APIs | Each service is stateless apart from files and kb, so more replicas can run behind the proxy or a Kubernetes Service | Built for every service except files and kb |
| files and kb | Their bytes are on a volume one replica can write, so they run one replica each | Partial |
| Crash recovery | A run's lease expires 15 seconds after its worker stops, and another worker continues it from its last saved step | Built |
| One tenant's load starving another's | Per-tenant caps on running runs | Planned |

## What to watch

| Signal | Why it matters | Healthy |
|---|---|---|
| The work queue | Rows waiting to be claimed mean the workers are busy or down | Claimed within a second or two |
| Crashed and recovered runs | Each crash re-runs a step and its model calls | Rare, each followed by a recovery |
| Tool calls left running | The gateway stopped mid-write, so the effect on your system is unknown | None; each one needs a person to check the system it called |
| Overdue tasks | People are not keeping up with the queue | Within the deadlines your workflows set |
| Model spend against budgets | A spent key stops new work | Below each key's cap |
| Database size and write load | Saved run state grows with open work | Steady; prune and vacuum on a schedule |
| Clock | Leases and timers use the database's clock; hosts must agree with it | Skew well under 15 seconds |

## Rotating keys

| Key | Steps |
|---|---|
| Approval key (`OPS_REVIEW_KEY`) | Set the new value for agents and tools and restart both. Approvals in flight must be given again |
| A service's signing key | Give the service a new key and key id, add its public key to every other service's trusted list beside the old one, restart the others, then the service; then remove the old key id and restart the others again |
| Sign-in token key (`OPS_PLATFORM_SIGNING_KEY`) | Set a new key and key id and restart every service; people may need to sign in again |
| Secrets key (`OPS_SECRETS_KEY`) | Changing it makes every stored credential unreadable, so each must be entered again. A rotation that re-encrypts them is planned |
| A provider's model key | The Security admin replaces it in the credential store; no restart |
| Database passwords | Change each login's password, update its setting, restart that service |
