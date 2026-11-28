# Install Ops AI from this package

Status: current. Every command below runs from the unpacked package folder; nothing needs the source repository, a
registry or the internet. The same steps are proven by `make release-proof` (see
[Install offline from a release package](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/release-package.md)).

The install script (`install.sh`) is not in the package. It lives in the repository, so the package installs with
Compose and your DBA's scripts. The full guide (architecture, security, operating) is in the repository under
`docs/guide/`; where it says `./install.sh`, use the Compose commands in [Operate](#operate) instead.

## Before you start

| Item | What you need |
|---|---|
| A host | Linux with Docker Engine 24 or newer, Docker Compose 2.22 or newer, `tar` and `curl`; 4 GB of memory for the containers and 15 GB of free disk |
| PostgreSQL | 15 or newer with the `vector` extension (pgvector 0.5 or newer), and an admin login your DBA controls. Azure Database for PostgreSQL Flexible Server works. SQL Server and Azure SQL are not supported for an install yet; `db/azure-sql/` is for review |
| A model endpoint | Any OpenAI-compatible endpoint and its key |
| A DNS name and TLS | A name on your load balancer or reverse proxy, forwarding to the one port Ops AI publishes. There is no TLS inside |

## 1. Check the files

Next to the downloaded archives:

```bash
shasum -a 256 -c ops-ai-<version>.SHA256SUMS
tar xzf ops-ai-<version>.tar.gz
cd ops-ai-<version>
shasum -a 256 -c SHA256SUMS
```

## 2. Load the images

```bash
docker load -i ../ops-ai-<version>-images.tar.gz
```

To use your own registry instead, push each image listed in `images.txt` there and set `OPS_IMAGE_PREFIX` in step 4.

## 3. Install the database

Your DBA applies `db/postgres/` in the order its `README.md` gives: `roles.sql`, a password for each login,
`CREATE DATABASE ops OWNER ops_migrator`, `CREATE EXTENSION vector` in that database, then `bundle.sql` and
`grants.sql` as `ops_migrator`. Every service refuses to start on a schema older than its build.

## 4. Write the settings file

```bash
cp ops-ai.env.example ops-ai.env
chmod 600 ops-ai.env
PREFIX=$(sed -n 's/^OPS_IMAGE_PREFIX=//p' ops-ai.env)
TAG=$(sed -n 's/^OPS_IMAGE_TAG=//p' ops-ai.env)
docker run --rm --entrypoint python "$PREFIX/platform:$TAG" /app/deploy/fly/generate_keys.py
```

The template already names the images of this package. Copy the generated key lines into `ops-ai.env` over the empty
ones, then set at least:

| Setting | Value |
|---|---|
| `OPS_PUBLIC_ORIGIN`, `OPS_PUBLIC_PORT` | The address people open, and the one port the proxy publishes |
| `OPS_DATABASE_URL_PLATFORM`, `_AGENTS`, `_TOOLS`, `_MODELS`, `_KB`, `_FILES`, `_DOCUMENTS` | Each service's own login, as `postgresql+asyncpg://<login>:<password>@<host>:5432/ops?ssl=require` |
| `OPS_BOOTSTRAP_TENANT_NAME`, `OPS_BOOTSTRAP_ADMIN_EMAIL`, `OPS_BOOTSTRAP_ADMIN_NAME`, `OPS_BOOTSTRAP_ADMIN_PASSWORD` | The organisation and the first admin (a password of 12 characters or more) |

## 5. Start it

```bash
C="docker compose -p ops-ai -f compose/app.yaml -f compose/dba.yaml --env-file ops-ai.env"
$C up -d migrate platform tools models kb files opa
```

`dba.yaml` makes the first job create only the first admin, on the platform service's own login, because your DBA
already applied the schema. To try Ops AI without a database or a provider, add `-f compose/try.yaml --profile postgres
--profile fake-model` to `C` and set `OPS_TRY_POSTGRES_PASSWORD` (see
[Install with Docker Compose](https://github.com/chanl-ai/ops-ai/blob/main/docs/deploy/compose.md#try-it-without-a-database-or-a-provider)).

## 6. Connect a model

Run once for agents and once for documents (`--key-id purpose:documents`); put the two printed keys in `ops-ai.env`
as `OPS_MODELS_KEY_AGENTS` and `OPS_MODELS_KEY_DOCUMENTS`, then start everything.

```bash
# Signs in as the first admin, who owns the account's model setup; it asks for the password.
$C run --rm --no-deps -e OPS_INSTALL_ADMIN_EMAIL=<first admin email> agents python /app/deploy/fly/connect_model.py \
  --models-url http://models:8730 --base-url <endpoint>/v1 --key-ref <name of the stored key> --alias default \
  --model <provider model id> --input-price <per million tokens> --output-price <per million tokens> --budget <cap> \
  --key-id purpose:agents --password-stdin
$C up -d
```

Save the provider's key in the console under Settings > Models > Connections, with the name you gave `--key-ref`. The agents
service reports unhealthy until a model is connected.

## 7. Check it

```bash
$C ps
curl -fsS "$OPS_PUBLIC_ORIGIN/api/platform/v1/health"
```

Then open the public address and sign in as the first admin.

## Operate

| Task | Command (from the package folder) |
|---|---|
| Status | `$C ps` |
| Logs | `$C logs --since 1h [service]` |
| Stop | `$C down` (keeps the volumes; `down -v` deletes the data) |
| Upgrade | Unpack the next package beside this one; your DBA applies its `db/postgres/upgrade-from-<your version>/upgrade.sql` and `grants.sql`; load its images; point `OPS_IMAGE_TAG` at the new version; `$C up -d` |
| Back up | The database with `pg_dump`, the `files-data` and `kb-data` volumes, and `ops-ai.env` (the secrets key in it unlocks every stored credential) |
