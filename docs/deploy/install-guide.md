# Install Ops AI by Elemente on your own servers

Status: current for the release package this file ships in (INSTALL.md). Every command below was run, in this order,
by the package's proof (`deploy/release/proof.sh`, c-385); values in angle brackets are yours to fill in. A shareable
page with the same content: `client-install-guide.html`.

Your team wants to run Ops AI inside your own network, on ordinary Linux machines with Docker, against a database your
DBA controls, and without our source code. This guide takes you from the downloaded package to a working sign-in,
and says which parts your DBA reviews and applies.

## What Ops AI is

Ops AI is an operational AI platform: AI agents and workflows that do back-office work, with a person approving every
action that changes something outside it. People use one web console to see what the agents did, decide what waits
on them, and configure agents, workflows, tools, knowledge and documents. Every write to another system goes through a
gateway that checks an approval, and every record is kept per tenant and team.

## What runs today

| Part | State |
|---|---|
| Ten container images for Linux on x86-64 (amd64), in one file you load with `docker load` | Runs today |
| Docker Compose files: every service, the workflow worker, the console, a policy engine and one web entry point | Runs today |
| PostgreSQL 16 or newer, including Azure Database for PostgreSQL Flexible Server | Runs today. Your DBA applies the schema from the scripts in `db/postgres/` |
| Azure SQL Database and SQL Server | Not yet runnable. The scripts in `db/azure-sql/` are for your DBA to review now (see "Azure SQL") |
| A model | Any OpenAI-compatible endpoint you choose. The package also holds a test model that answers from fixed rules and calls no provider |

## What is in the package

| File | What it is |
|---|---|
| `ops-ai-<version>.tar.gz` | This package: `INSTALL.md`, `compose/`, `ops-ai.env.example`, `db/`, `images.txt`, `release.txt`, `SHA256SUMS` |
| `ops-ai-<version>-images.tar.gz` | The ten images. `images.txt` lists each image's name and id |
| `ops-ai-<version>.SHA256SUMS` | Checksums of the two files above |
| `compose/app.yaml` | Every service; only the entry point publishes a port |
| `compose/dba.yaml` | Use it when your DBA applied the schema: no container then holds a login that can change the schema |
| `compose/try.yaml` | For trying it out only: the test model (profile `fake-model`) and a built-in PostgreSQL (profile `postgres`) |
| `ops-ai.env.example` | Every setting, each with a comment |
| `db/postgres/` | The PostgreSQL scripts your DBA applies |
| `db/azure-sql/` | The Azure SQL scripts, for review only |

## Machines

| Item | What you need |
|---|---|
| Virtual machines | One Linux VM runs everything. Start with 4 vCPUs, 8 GB of memory and 60 GB of disk; in the proof every container together used about 1.8 GB of memory at rest. A second VM with the same package loaded is a standby you start from a backup |
| Operating system | Any current 64-bit Linux on x86-64 (amd64) that runs Docker, for example Ubuntu 22.04 or 24.04, or RHEL 9 |
| Docker | Docker Engine 24 or newer with the Compose plugin 2.22 or newer (`docker compose version`) |
| Inbound ports | One: the entry point, `OPS_PUBLIC_PORT` (8890 unless you change it), reached only from your TLS terminator or load balancer |
| Outbound access | Your PostgreSQL server (5432); your model endpoint (usually 443); your mail server if you send mail. Nothing else: the images are loaded from the file, so the VM needs no registry or internet access |
| TLS and DNS | A DNS name such as `ops.example.com` on your load balancer or reverse proxy, which ends TLS and forwards to the VM's entry point port. Set `OPS_PUBLIC_ORIGIN=https://ops.example.com` |
| Your workstation for the DBA steps | `psql` that can reach the database server |

## Database

Ops AI stores everything in one PostgreSQL database. Your DBA applies the schema in your own change window, and the
services connect with logins that can read and write rows but cannot change the schema.

### Azure Database for PostgreSQL

| Setting | Value |
|---|---|
| Deployment | Flexible Server |
| PostgreSQL version | 16 or newer. On 15 and older the server admin cannot create the one role that needs BYPASSRLS, and `roles.sql` stops there |
| Size | A starting point: General Purpose, 2 vCores, 8 GB memory, 64 GB storage. Measure and resize |
| Network | Private access from the Ops AI VM's network; no public endpoint needed |
| TLS | Required (the Azure default). Every connection string below ends in `?ssl=require` or `sslmode=require` |
| Extensions | None |
| Backups | Azure's automated backups with point-in-time restore, at the retention your policy sets |

### The logins

| Login | Who uses it | Rights |
|---|---|---|
| Your server admin | The DBA, for the steps below | Creates the roles and the database. Not a superuser on Azure |
| `ops_migrator` | The DBA, to apply and upgrade the schema | Owns every table, index and policy; cannot create roles or databases |
| `ops_platform_runtime`, `ops_agents_runtime`, `ops_tools_runtime`, `ops_models_runtime`, `ops_kb_runtime`, `ops_files_runtime`, `ops_documents_runtime` | One per service | Read and write rows in that service's own tables. No DDL: `CREATE TABLE`, `DROP TABLE` and `ALTER TABLE` are refused. Row-level security applies |
| `ops_runtime_tenant`, `ops_runtime_system`, `ops_platform_tenant`, `ops_platform_lookup` | The services switch to these inside a transaction | No login. `ops_runtime_system` reads across tenants and is used only by the agents service's background loops |

### Tenant isolation

Every table that holds customer data carries a `tenant_id` column and a row-level security policy that admits only
rows whose `tenant_id` equals the tenant the transaction set. The policies are forced, so they apply to the table
owner too. The tenant comes from the signed-in person's token, never from a request body.

### What the DBA runs, in order

In the folder `db/postgres/` of the unpacked package. `<admin>` is your server admin; `<host>` is your server's name.

| Step | Connect as | Command |
|---|---|---|
| 1 | Server admin | `psql -v ON_ERROR_STOP=1 "host=<host> port=5432 user=<admin> dbname=postgres sslmode=require" -f roles.sql` |
| 2 | Server admin | `psql -v ON_ERROR_STOP=1 "<same as step 1>" -c "ALTER ROLE <login> PASSWORD '<password>'"` once for each of the eight logins in the table above |
| 3 | Server admin | `psql -v ON_ERROR_STOP=1 "<same as step 1>" -c "GRANT ops_migrator TO <admin>"` |
| 4 | Server admin | `psql -v ON_ERROR_STOP=1 "<same as step 1>" -c "CREATE DATABASE ops OWNER ops_migrator"` |
| 5 | `ops_migrator` | `psql -v ON_ERROR_STOP=1 "host=<host> port=5432 user=ops_migrator dbname=ops sslmode=require" -f bundle.sql` |
| 6 | `ops_migrator` | `psql -v ON_ERROR_STOP=1 "<same as step 5>" -f grants.sql` |

`01-agents.sql` to `07-documents.sql` are each service's part of `bundle.sql`, for review. `manifest.json` names each
part's version; `sha256sum -c SHA256SUMS` checks the files.

## Install

On the VM, as a user that may run Docker, in a folder only your operators can read.

1. Check and unpack the files you copied to the VM.

   ```
   sha256sum -c ops-ai-<version>.SHA256SUMS
   tar -xzf ops-ai-<version>.tar.gz
   cd ops-ai-<version>
   sha256sum -c SHA256SUMS
   ```

2. Load the images, then compare `docker images` with `images.txt`.

   ```
   docker load -i ../ops-ai-<version>-images.tar.gz
   ```

3. Make the settings file from the template.

   ```
   cp ops-ai.env.example ops-ai.env
   chmod 600 ops-ai.env
   docker run --rm --entrypoint python <OPS_IMAGE_PREFIX>/platform:<version> /app/deploy/fly/generate_keys.py
   ```

   The last command prints the signing keys. Put each printed line in `ops-ai.env` in place of the empty line with the
   same name. Then set these:

   | Setting | Value |
   |---|---|
   | `OPS_PUBLIC_ORIGIN` | The address people open, for example `https://ops.example.com` |
   | `OPS_PUBLIC_PORT` | The entry point's port on the VM |
   | `OPS_DATABASE_URL_PLATFORM` and the six other `OPS_DATABASE_URL_<SERVICE>` | `postgresql+asyncpg://ops_<service>_runtime:<password>@<host>:5432/ops?ssl=require` |
   | `OPS_DATABASE_URL` | Leave empty |
   | `OPS_BOOTSTRAP_TENANT_NAME`, `OPS_BOOTSTRAP_ADMIN_EMAIL`, `OPS_BOOTSTRAP_ADMIN_NAME`, `OPS_BOOTSTRAP_ADMIN_PASSWORD` | Your organisation's name and the first admin; the password has at least 12 characters |

4. Start everything except the agents.

   ```
   C="docker compose -p ops-ai -f compose/app.yaml -f compose/dba.yaml --env-file ops-ai.env"
   $C up -d --wait --wait-timeout 600 migrate platform tools models kb files opa
   ```

   The first job makes the first tenant, its Security team and the admin. Every service checks the database's schema
   version and refuses to start when it is older than the service.

5. Connect a model. This binds the name `default` to your OpenAI-compatible endpoint and prints a key once; run it
   twice, once per key id.

   ```
   $C run --rm -T --no-deps agents python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
     --base-url <endpoint>/v1 --alias default --model <model id> --input-price <per million tokens> \
     --output-price <per million tokens> --budget <spending cap> --key-id purpose:agents
   ```

   Put the printed `OPS_MODELS_KEY` value in `OPS_MODELS_KEY_AGENTS`, run it again with `--key-id purpose:documents`
   and put that value in `OPS_MODELS_KEY_DOCUMENTS`. When your endpoint needs a key, the Security admin stores it in
   Settings > Secrets and you add `--key-ref <its name>`; the proof used the test model, which needs none.

6. Start the rest.

   ```
   $C up -d --wait --wait-timeout 600
   ```

To try the package before your database and model are ready, add `-f compose/try.yaml --profile fake-model` to `C`
and connect the model with `--base-url http://fake-model:8746/v1 --model fake-chat --input-price 1 --output-price 1
--budget 5`. The test model answers from fixed rules and is not for production.

## Check it works

| Check | Command or action | Expected |
|---|---|---|
| Every container healthy | `$C ps` | Each service `Up` and `(healthy)`; the migrate job exited 0 |
| The entry point answers | `curl -fsS <OPS_PUBLIC_ORIGIN>/api/platform/v1/health` | A JSON body with `"success":true` |
| Sign in | Open `OPS_PUBLIC_ORIGIN` and sign in as the first admin | The console opens |
| Every page | Open each item in the left menu | Each page loads with no error message |

After the first sign-in, the admin changes the password; then remove `OPS_BOOTSTRAP_ADMIN_PASSWORD` from `ops-ai.env`.

## Upgrade and roll back

| Step | Who | What |
|---|---|---|
| 1 | DBA | Back up the database (below) |
| 2 | Operator | Load the new release's images with `docker load` |
| 3 | DBA | Run the new release's `db/postgres/upgrade-from-<your version>/upgrade.sql` as `ops_migrator`, then its `grants.sql`. Each step checks the version it starts from and stops before any change when the database is elsewhere |
| 4 | Operator | Set `OPS_IMAGE_TAG` to the new version and run `$C up -d --wait --wait-timeout 600` |

This release is the first, so it holds no upgrade script; each later release ships one from the versions before it.
To roll back, restore the backup from step 1 and set `OPS_IMAGE_TAG` back. A service of the older release refuses to
start on the newer schema, so the two cannot be mixed by mistake.

## Back up and restore

On Azure, the automated backups and point-in-time restore cover the database. For a copy you hold yourself, back up
as the server admin: the tenant policies apply to the schema's owner, so `pg_dump` as `ops_migrator` stops with a
row-level security error. Use `pg_dump` of your server's version or newer; the `postgres` image carries one.

```
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_dump -Fc -f /backup/ops.dump "host=<host> port=5432 user=<admin> dbname=ops sslmode=require"
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/out" alpine tar czf /out/files-data.tgz -C /data .
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/out" alpine tar czf /out/kb-data.tgz -C /data .
```

Keep `ops-ai.env` with the backup: `OPS_SECRETS_KEY` unlocks the stored credentials, and without it they are lost.

To restore into a new database:

```
$C stop
psql -v ON_ERROR_STOP=1 "host=<host> port=5432 user=<admin> dbname=postgres sslmode=require" -c "CREATE DATABASE ops_restored OWNER ops_migrator"
docker run --rm -e PGPASSWORD=<admin password> -v "$PWD/backup:/backup" postgres:17 \
  pg_restore --exit-on-error -d "host=<host> port=5432 user=<admin> dbname=ops_restored sslmode=require" /backup/ops.dump
docker run --rm -v ops-ai_files-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/files-data.tgz -C /data"
docker run --rm -v ops-ai_kb-data:/data -v "$PWD/backup:/in" alpine sh -c "rm -rf /data/* && tar xzf /in/kb-data.tgz -C /data"
```

Point the seven `OPS_DATABASE_URL_<SERVICE>` settings at `ops_restored`, then `$C up -d --wait --wait-timeout 600`.

## Security notes

| Area | What holds |
|---|---|
| Secrets | All in `ops-ai.env` (mode 600), or each as a file under `/run/secrets` named after the setting in lower case, for Docker secrets. No image holds a secret |
| Keys | One signing key per service, handed only to that service; `OPS_PLATFORM_SIGNING_KEY` signs sign-in tokens; `OPS_REVIEW_KEY` signs approvals; `OPS_SECRETS_KEY` seals stored credentials. Keep them out of tickets and chat |
| Database | Each service has its own login with row rights on its own tables only; no running container can change the schema; row-level security separates tenants |
| Network | Only the entry point publishes a port. The services, the policy engine and platform-service's internal port stay on the Compose project's private network. Put TLS in front of the entry point |
| Outbound calls | Tool calls leave only through the tools service, under its policy engine; model calls only through the models service |
| Containers | Every image runs as a non-root user (uid 10001) |
| First admin | Remove `OPS_BOOTSTRAP_ADMIN_PASSWORD` once the admin has signed in and changed it |

## Azure SQL

| Ready for your DBA's review now, in `db/azure-sql/` | Still to come |
|---|---|
| `roles.sql`: one SQL login per service and `ops_migrator`; the database with collation `Latin1_General_100_BIN2_UTF8` and `READ_COMMITTED_SNAPSHOT ON` | Applying these scripts to an Azure SQL database and comparing the result with the services' models |
| `01-agents.sql` to `07-documents.sql` and `bundle.sql`: every table, index and key, and a security policy per tenant table | Running the services on Azure SQL and SQL Server |
| `grants.sql`: each service's user with SELECT, INSERT, UPDATE and DELETE on its own tables only | Full-text search for knowledge bases, the workflow checkpoint tables and the queue claim under the tenant policy |

The scripts are generated from the services' models and checked against reviewed copies, but they have never been
applied to a server, and Ops AI does not run on SQL Server yet. Install on PostgreSQL today.

## Support

Support contact: `<name, email and hours to be added>`.
