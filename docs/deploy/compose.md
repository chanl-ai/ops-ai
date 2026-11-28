# Install with Docker Compose

Status: current. Proven on one machine; not yet run on a client's servers.

Run Ops AI's containers yourself with Docker Compose, when you want every setting in your own hands or your change
process does not allow an install script. The [install script](install.md) runs these same steps for you.

## Before you start

| Item | What you need |
|---|---|
| A host | Linux with Docker Engine 24 or newer and Compose 2.22 or newer ([Sizing](../guide/deployment-options.md#sizing)) |
| The files | A clone at the release tag: `git clone --branch v1.0.0 https://github.com/chanl-ai/ops-ai.git`. The commands below run from its root. An unpacked [release package](release-package.md) holds the same files under `compose/`, with the template as `ops-ai.env.example` |
| PostgreSQL | 15 or newer, with the schema applied by your DBA ([Database](database.md)), or a superuser login the schema job applies it with |
| A model endpoint | Any OpenAI-compatible endpoint and its key |

## Install

<!-- site: steps -->
1. **Write the settings file** outside the folder, and generate the keys into it.

   ```bash
   cp deploy/compose/app.env.example ~/ops-ai.env
   docker run --rm --entrypoint python ghcr.io/chanl-ai/ops-ai/platform:1.0.0 \
     /app/deploy/fly/generate_keys.py >> ~/ops-ai.env
   ```

   Every setting is listed in the file with a comment. Delete the empty key lines the generated ones replace, then set
   at least `OPS_PUBLIC_ORIGIN`, `OPS_PUBLIC_PORT`, `OPS_IMAGE_PREFIX=ghcr.io/chanl-ai/ops-ai`, `OPS_IMAGE_TAG=1.0.0`, the database settings and the six
   `OPS_BOOTSTRAP_*` values that name the organisation and the first admin.

2. **Start it.**

   ```bash
   C="docker compose -p ops-ai -f deploy/compose/app.yaml --env-file $HOME/ops-ai.env"
   $C up -d
   ```

   The schema job runs first and every service waits for it. When your DBA applies the schema, add
   `-f deploy/compose/dba.yaml` to `C`: the job then only creates the first admin, and each service uses its own login.

3. **Connect a model** (below), then put TLS in front of the published port and sign in as the first admin.

## Connect a model

The connect step signs in as the first admin, binds the account's model alias `default` to your endpoint and prints a
model key once. It asks for the admin's password (or reads it from stdin), never from the command line. Run it for
agents and for documents, put the two keys in the settings file, and start again. Later changes to the model are made
on Settings › Workspace › Models.

```bash
$C run --rm --no-deps -e OPS_INSTALL_ADMIN_EMAIL=<first admin email> agents python /app/deploy/fly/connect_model.py \
  --models-url http://models:8730 --base-url <endpoint>/v1 --key-ref <name of the stored key> --alias default \
  --model <provider model id> --input-price <per million tokens> --output-price <per million tokens> --budget <cap> \
  --key-id purpose:agents --password-stdin
# again with --key-id purpose:documents; set OPS_MODELS_KEY_AGENTS and OPS_MODELS_KEY_DOCUMENTS
$C up -d
```

Save the provider's key in the console under Settings > Models > Connections, with the name you gave `--key-ref`. Outside
development, Ops AI refuses a provider key in the settings file. The agents service reports unhealthy until a model is
connected.

## Try it without a database or a provider

`deploy/compose/try.yaml` adds a PostgreSQL container and a test model that answers from fixed rules and calls no
provider. Set `OPS_TRY_POSTGRES_PASSWORD` and point `OPS_DATABASE_URL` at
`postgresql+asyncpg://ops:<that password>@postgres:5432/ops`, then:

```bash
C="$C -f deploy/compose/try.yaml --profile postgres --profile fake-model"
$C up -d
```

Connect the model with `--base-url http://fake-model:8746/v1 --model fake-chat --input-price 1 --output-price 1
--budget 5`.

## Keep secrets in files

Any setting may instead be a file under `/run/secrets` named after it in lower case, read when the setting is empty.
In a Compose override file:

```yaml
services:
  platform:
    secrets: [{ source: platform_signing_key, target: ops_platform_signing_key }]
secrets:
  platform_signing_key: { file: /etc/ops-ai/platform_signing_key }
```

## Options

| Setting | What it does | Default |
|---|---|---|
| `OPS_PUBLIC_ORIGIN` | The address people open, as your TLS terminator serves it | none |
| `OPS_PUBLIC_PORT` | The one port the proxy publishes | 8890 |
| `OPS_IMAGE_PREFIX`, `OPS_IMAGE_TAG` | Where the images come from and which version | Local names; set them to the registry and release |
| `OPS_FILES_SCANNING` | How uploads are scanned: `eicar` (a test engine), or `hook` for your own scanner. `off` is refused outside development | `eicar` |
| `OPS_FLAGS` | Features turned on ([Feature flags](install.md#turn-on-a-feature-flag)) | none |
| `OPS_MAIL_PROVIDER`, `OPS_SMTP_*` | Mail for invites and password resets | none |

Files and knowledge bytes are stored on the `files-data` and `kb-data` volumes until a Security admin points storage at
a bucket in Settings > Storage.

## Limits

- No TLS inside: put your own TLS terminator or load balancer in front of the published port.
- The app that serves chat widgets on your other sites has no image yet.
- Each Python image carries every service's code; smaller images per service are planned.

## Next

<!-- site: cards -->
- **[Monitor](monitoring.md)**: Status, health and logs of each container.
- **[Upgrade](upgrade.md)**: Move to a new release and roll back.
- **[Back up and restore](backup-and-restore.md)**: The database, the stored files and the keys.
