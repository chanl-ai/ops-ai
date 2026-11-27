# Install with Docker Compose

Status: current.

Some teams cannot run an install script on a production machine, because their change process wants every setting and
every command reviewed first. Docker Compose gives you that: you write the settings file, start the containers
yourself and choose each option. The [install script](install.md) runs these same steps for you. This page is for the
case where you want to run them yourself, on one machine. The steps have run end to end on one machine and have not yet
run on a client's servers.

## What you need before you start

| Item | What you need |
|---|---|
| A host | Linux with Docker Engine 24 or newer and Compose 2.22 or newer ([Sizing](../guide/deployment-options.md#sizing)) |
| The files | A clone at the release tag: `git clone --branch v1.2.0 https://github.com/chanl-ai/ops-ai.git`. The commands below run from its root. An unpacked [release package](release-package.md) holds the same files under `compose/`, with the settings template as `ops-ai.env.example` |
| PostgreSQL | 15 or newer with the `vector` extension available. Either your DBA applies the schema ([Database](database.md)), or you give the install a login that may change it |
| A model endpoint | Any OpenAI-compatible endpoint and its key |

## Start Ops AI

<!-- site: steps -->
1. **Write the settings file** outside the repository folder, and generate the keys into it.

   ```bash
   cp deploy/compose/app.env.example ~/ops-ai.env
   docker run --rm --entrypoint python ghcr.io/chanl-ai/ops-ai/platform:1.2.0 \
     /app/deploy/fly/generate_keys.py >> ~/ops-ai.env
   ```

   The file lists every setting with a comment. Delete the empty key lines that the generated ones replace. Then set at
   least these:

   - `OPS_PUBLIC_ORIGIN` and `OPS_PUBLIC_PORT`: the address people open and the one port the proxy publishes.
   - `OPS_IMAGE_PREFIX=ghcr.io/chanl-ai/ops-ai` and `OPS_IMAGE_TAG=1.2.0`.
   - The database: `OPS_DATABASE_URL` for a login that may change the schema, or the seven
     `OPS_DATABASE_URL_<SERVICE>` lines when your DBA applied it.
   - `OPS_BOOTSTRAP_TENANT_NAME`, `OPS_BOOTSTRAP_TEAM_NAME`, `OPS_BOOTSTRAP_ADMIN_EMAIL`, `OPS_BOOTSTRAP_ADMIN_NAME` and
     `OPS_BOOTSTRAP_ADMIN_PASSWORD` (12 characters or more), which name the organisation and the first admin. Leave
     `OPS_BOOTSTRAP_TENANT_ID` at `local`.

2. **Start it.**

   ```bash
   C="docker compose -p ops-ai -f deploy/compose/app.yaml --env-file $HOME/ops-ai.env"
   $C up -d
   ```

   The schema job runs first and every service waits for it. When your DBA applies the schema, add
   `-f deploy/compose/dba.yaml` to `C`. The job then only creates the first admin, and each service uses its own login.

3. **Connect a model** (next section), put TLS in front of the published port, and sign in as the first admin.

## Connect a model

Agents cannot answer until a model is connected. The connect step binds the model alias `default` to your endpoint and
prints a model key once. Run it for agents and for documents, put the two keys in the settings file, and start again.

```bash
$C run --rm -T --no-deps agents python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
  --base-url <endpoint>/v1 --key-ref <name of the stored key> --alias default --model <provider model id> \
  --input-price <per million tokens> --output-price <per million tokens> --budget <cap> --key-id purpose:agents
# Run it again with --key-id purpose:documents.
# Set OPS_MODELS_KEY_AGENTS and OPS_MODELS_KEY_DOCUMENTS in the settings file, then:
$C up -d
```

Each run prints one line, `OPS_MODELS_KEY=<secret>`, and shows it only once. If a key with that id already exists, the
script says so and prints nothing to copy.

The provider's own key is saved in the console, under Settings › Models › Connections, with the name you gave
`--key-ref`. Ops AI refuses a provider key in the settings file outside development. The agents service reports
unhealthy until a model is connected.

A third key, `OPS_MODELS_KEY_KB`, lets the knowledge service embed documents for search by meaning. It also needs an
embedding alias ([Set the embedding model](install.md#set-the-embedding-model)). Without them, search uses keywords.

## Try it without a database or a provider

For a first look, the trial file adds a PostgreSQL container and a test model that answers from fixed rules and calls
no provider. Set `OPS_TRY_POSTGRES_PASSWORD` and point `OPS_DATABASE_URL` at
`postgresql+asyncpg://ops:<that password>@postgres:5432/ops`, then:

```bash
C="$C -f deploy/compose/try.yaml --profile postgres --profile fake-model"
$C up -d
```

Connect the model with `--base-url http://fake-model:8746/v1 --model fake-chat --input-price 1 --output-price 1
--budget 5`, and leave out `--key-ref`. Do not use the trial file in production.

## Keep secrets in files

Any setting may instead be a file under `/run/secrets` named after it in lower case. Ops AI reads the file when the
setting is empty. In a Compose override file:

```yaml
services:
  platform:
    secrets: [{ source: platform_signing_key, target: ops_platform_signing_key }]
secrets:
  platform_signing_key: { file: /etc/ops-ai/platform_signing_key }
```

## Settings you will change

| Setting | What it does | Default |
|---|---|---|
| `OPS_PUBLIC_ORIGIN` | The address people open, as your TLS terminator serves it | none |
| `OPS_PUBLIC_PORT` | The one port the proxy publishes | 8890 |
| `OPS_IMAGE_PREFIX`, `OPS_IMAGE_TAG` | Where the images come from and which version | Local names, so set both to your registry and the release |
| `OPS_FILES_SCANNING` | How uploads are scanned: `eicar` (a test engine) or `hook` for your own scanner. `off` is refused outside development | `eicar` |
| `OPS_FLAGS` | The features turned on ([Feature flags](install.md#turn-on-a-feature-flag)) | none |
| `OPS_MAIL_PROVIDER`, `OPS_MAIL_FROM`, `OPS_SMTP_*` | Mail for invites and password resets: `none`, `smtp`, `resend` or `graph` | `none` |
| `OPS_PLUGINS_HOST_DIR` | The host folder that the tools and knowledge services mount read-only as their plugins folder | `plugins/` in the clone |

Files and knowledge bytes live on the `files-data` and `kb-data` volumes until a Security admin points storage at a
bucket in Settings › Workspace › Storage.

## What success looks like

`$C ps` lists every service as running, and the ones with health checks as healthy. Opening your address shows the sign-in
page, and the first admin can sign in. Health is also at `/api/platform/v1/health` on the published port.

## Limits

- Ops AI has no TLS inside. Put your own TLS terminator or load balancer in front of the published port.
- With a release package, the default plugins folder is two levels above the package's `compose/` folder, outside the
  package. Set `OPS_PLUGINS_HOST_DIR` to a folder you own, even an empty one, or Docker creates the default folder
  there as root.
- The app that serves chat widgets on your other sites has no image yet.
- Each Python image carries every service's code. Smaller images per service are planned.

## Next

<!-- site: cards -->
- **[Monitor](monitoring.md)**: Status, health and logs of each container.
- **[Upgrade](upgrade.md)**: Move to a new release and roll back.
- **[Back up and restore](backup-and-restore.md)**: The database, the stored files and the keys.
