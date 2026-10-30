# Ops AI on Docker Compose

Status: current. Proven on one machine; not yet run on a bank's servers. A client team installs from a
[release package](release-package.md) instead, with prebuilt images and no checkout.

<!-- Built by an earlier change; the proof is deploy/compose/proof.sh. -->

Compose runs every service, the workflow worker, the console, OPA and one proxy as containers against a PostgreSQL the
bank runs. Nothing runs from the repository's development scripts. Compose is optional: every release still runs on
one machine with no container runtime ([deployment targets](../architecture/service-map.md#deployment-targets)).

The files are in `deploy/compose/` and `deploy/images/`, and the image stages in `deploy/fly/Dockerfile`.

## What runs

![One origin in front of the services on one machine, against your PostgreSQL, your model endpoint and your bank systems](../diagrams/deployment.svg)

| Service | Image (`deploy/fly/Dockerfile` target) | Port inside | Reached as | Health check |
|---|---|---|---|---|
| migrate | platform, command `migrate` | none | one-shot: every chain, then the first admin | exit 0 |
| platform | platform | 8710, 8711 | `/api/platform/`; 8711 (API-key introspection) only on the private network | `/v1/health` |
| agents | agents | 8700 | `/api/agents/` | `/health`, 503 until a model is connected |
| worker | agents, `python -m ops_agents.api.worker` | none | none | a database query |
| tools | tools | 8720 | `/api/tools/` | `/health` |
| models | models | 8730 | not routed: no browser calls it | `/health` |
| kb | kb | 8740 | `/api/kb/` | `/health` |
| files | files | 8750 | `/api/files/` | `/health` |
| documents | documents | 8760 | `/api/documents/` | `/health` |
| runner | runner (code tools' functions on WASM; no database) | 8770 | tools-service only | `/health` |
| opa | opa (OPA with `services/tools-service/policy`) | 8181 | tools-service only | none (a static binary image) |
| console | console | 3016 | `/` | `/login` |
| proxy | proxy (Caddy, `deploy/fly/Caddyfile`) | 8080, published as `OPS_PUBLIC_PORT` | the one origin | `/api/platform/v1/health` |

Every image runs as uid 10001. The seven Python images are one base (every service's dependencies and source) plus a
command, port and health check each, so they share every heavy layer: about 626 MB on disk once, not seven times. The
console image is about 440 MB.

## Facts that shape it

| Fact | Consequence |
|---|---|
| The console is built once with a placeholder per service URL | `deploy/images/console-start.mjs` writes the container's `NEXT_PUBLIC_OPS_*_URL` values in at every start, from a pristine copy, so one image serves any host; it refuses to start with one unset |
| Services listen on `OPS_BIND_HOST` (default 127.0.0.1) | The images set 0.0.0.0; the proxy is the only published port |
| API keys are introspected on platform's internal port | `OPS_PLATFORM_INTERNAL_URL=http://platform:8711`; that port is on the project network, never published, and each call needs a service token. Checked once by hand: kb-service accepted an API key (200) and refused a tampered one (401) |
| Agents migrations create a role with BYPASSRLS | The migrate job's user must be a superuser. Where the DBA applies the schema (`database.md`), add `-f deploy/compose/dba.yaml`: the migrate job then runs no migration and only makes the first admin, on platform-service's runtime login, and every service uses its own `OPS_DATABASE_URL_<SERVICE>` |
| `app.yaml` names images and builds nothing | A checkout adds `-f deploy/compose/build.yaml` to build them; a release package loads them from its bundle |
| `OPS_ENVIRONMENT=production` | Nothing is seeded; the migrate job makes the first tenant, Security team and admin; a first publish waits for a second person unless the team's publish policy says otherwise |
| Every setting reads env, or a file under `/run/secrets` named after it | Secrets come from the env file or Docker secrets; no image holds one; an empty value counts as unset. Reading a file is checked with `OPS_SECRETS_DIR`; a compose `secrets:` mount is **unverified** |
| `OPS_FILES_SCANNING=hook` leaves uploads pending with no scanner; `off` is refused outside development | The default here is `eicar` |
| Files and knowledge-base bytes are stored locally until a Security admin points storage at a bucket (Settings > Storage) | Volumes `files-data` and `kb-data` hold them |

## Run it from a clean clone

Needs Docker with Compose 2.22 or newer, about 6 GB for the image builds, and a PostgreSQL 15+ database whose user is
a superuser.

```
git clone <repo> ops-ai && cd ops-ai
for t in platform agents tools models kb files documents runner opa proxy console; do
  docker build -f deploy/fly/Dockerfile --target $t -t ops-ai/$t:dev .
done
cp deploy/compose/app.env.example ~/ops-ai.env             # outside the repo; never commit it
docker run --rm --entrypoint python ops-ai/platform:dev /app/deploy/fly/generate_keys.py >> ~/ops-ai.env
```

Edit `~/ops-ai.env`: every variable is listed there with a comment. The keys `generate_keys.py` appended replace the
empty key lines above them, so delete those. Set at least `OPS_PUBLIC_ORIGIN`, `OPS_PUBLIC_PORT`, `OPS_DATABASE_URL` and
the six `OPS_BOOTSTRAP_*` values. Then:

```
docker compose -p ops-ai -f deploy/compose/app.yaml --env-file ~/ops-ai.env up -d
```

The migrate job runs first and every service waits for it. agents-service reports unhealthy until a model is connected.

### Connect a model

`connect_model.py` binds the alias `default` to an OpenAI-compatible endpoint and prints a model key once. Run it for
agents-service and for documents-service, put the keys in the env file, and start again:

```
C="docker compose -p ops-ai -f deploy/compose/app.yaml --env-file $HOME/ops-ai.env"
$C run --rm --no-deps agents python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
  --base-url <endpoint>/v1 --key-ref <name in Secrets> --alias default --model <provider model id> \
  --input-price <per million> --output-price <per million> --budget <cap> --key-id purpose:agents
# again with --key-id purpose:documents; then set OPS_MODELS_KEY_AGENTS and OPS_MODELS_KEY_DOCUMENTS
$C up -d
```

A provider key is saved on Settings > Model providers (an account admin: an admin on the Security team) under the
`--key-ref` name; outside development models-service refuses keys in its env.

### Try it with a built-in database and the fake model

`deploy/compose/try.yaml` adds a PostgreSQL (profile `postgres`) and a fake OpenAI-compatible model (profile
`fake-model`) that answers from committed rules and calls no provider. Both were started by an earlier change: the PostgreSQL
profile through migrate, the first admin and a sign-in; the fake model through the full walk. Set `OPS_TRY_POSTGRES_PASSWORD` and
`OPS_DATABASE_URL=postgresql+asyncpg://ops:<that password>@postgres:5432/ops`, add `-f deploy/compose/try.yaml
--profile postgres --profile fake-model` to the commands above, and connect the model with
`--base-url http://fake-model:8746/v1 --model fake-chat --input-price 1 --output-price 1 --budget 5`.

### Secrets as files

Any setting may be a file under `/run/secrets` named after it in lower case, read when its env value is empty. For
example, in an override file:

```
services:
  platform:
    secrets: [{ source: platform_signing_key, target: ops_platform_signing_key }]
secrets:
  platform_signing_key: { file: /etc/ops-ai/platform_signing_key }
```

## Operate

| Task | How |
|---|---|
| Status | `$C ps` (each service's health in the STATUS column) |
| Logs | `$C logs -f <service>`, e.g. `agents`, `worker`, `migrate`; `$C logs --since 1h` for all |
| Upgrade | Build or pull the new images (same `OPS_IMAGE_TAG` or a new one), then `$C up -d`: the migrate job runs again before the services restart. Migrations do not roll back: an older image may fail on a newer schema, so restore the database to go back |
| Back up | The database: `pg_dump -Fc` of the DSN's database, as the bank backs up any PostgreSQL. File bytes: the `files-data` and `kb-data` volumes, e.g. `docker run --rm -v ops-ai_files-data:/data -v $PWD:/out alpine tar czf /out/files-data.tgz -C /data .`. Keep `OPS_SECRETS_KEY` with the backup: stored credentials cannot be read without it |
| Restore | Restore the database and both volumes, with the same keys in the env file, then `$C up -d` |
| Stop | `$C down` (volumes stay; `down -v` deletes them) |
| Prove an install | `OPS_SMOKE_EMAIL=<admin> OPS_SMOKE_PASSWORD=<password> node deploy/fly/smoke.mjs <origin>`: sign-in, a published agent's chat, an upload, a workflow run on the worker, a document read and three console pages. It invites a second person as approver to decide the publishes. The chat and the read spend from the model keys |
| Prove this checkout on this machine | `sh deploy/compose/proof.sh`: builds every image, starts project `ops-compose` on port 18890 against a fresh `ops_compose` database on the dev PostgreSQL (:5477) with the fake model, and runs the walk |

## Not covered

| Item | State |
|---|---|
| The embed app (`apps/embed`) | No image yet |
| Smaller images per service (each with only its own dependencies) | Not built: tools-service still imports agents-service, and settings find seed and policy files under the source tree |
| A registry, image signing and an SBOM per image | Not built |
| The use-case runner against a running stack | It starts its own services and database on every run, so the walk above proves the stack instead |
| TLS | The bank's terminator or load balancer in front of the proxy |
