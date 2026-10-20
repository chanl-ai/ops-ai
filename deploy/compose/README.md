# Compose

Two uses, two files. Runbook for the install: `docs/deploy/compose.md`.

| File | What it is |
|---|---|
| `app.yaml` | Ops AI as containers: every service, the workflow worker, the console, OPA and one proxy, against a PostgreSQL outside the file, on images named `<OPS_IMAGE_PREFIX>/<service>:<OPS_IMAGE_TAG>`. A one-shot migrate job runs before the services |
| `build.yaml` | Added to `app.yaml` in a checkout: builds each image from `deploy/fly/Dockerfile`. A release package ships prebuilt images and leaves it out |
| `dba.yaml` | Added to `app.yaml` when the DBA applied the schema (`deploy/database`): the migrate job only makes the first admin, on platform-service's runtime login |
| `app.env.example` | Every setting `app.yaml` reads, each with a comment; copy it outside the repo and fill it in |
| `try.yaml` | Optional, added to `app.yaml` for trying it out: a PostgreSQL (profile `postgres`) and the fake model (profile `fake-model`) |
| `proof.sh` | Builds every image, starts project `ops-compose` on :18890 against a fresh `ops_compose` database on the dev PostgreSQL, connects the fake model and walks the origin |
| `compose.yaml` | Local development dependencies only: PostgreSQL :5477, OPA :8181 and test mail servers, for services run on the host |

```bash
# The install (images: deploy/fly/Dockerfile, one target per service)
docker compose -p ops-ai -f deploy/compose/app.yaml -f deploy/compose/build.yaml --env-file ~/ops-ai.env up -d --build
docker compose -p ops-ai -f deploy/compose/app.yaml --env-file ~/ops-ai.env logs -f agents

# Development dependencies
make -C services/agents-service db-up      # or: docker compose -f deploy/compose/compose.yaml up -d --wait
make -C services/agents-service db-down
```

The development file's project name stays `ops-runtime` so its data volume is reused; it uses no env file. The install
reads only the env file it is given; never commit one.
