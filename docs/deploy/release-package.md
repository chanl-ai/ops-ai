# Release package: one download a client team installs from

Status: current. Built and proven by c-385 (`deploy/release/proof.sh`, evidence `.codeloop/evidence/385/proof.txt`);
not yet installed on a client's machines. The guide inside the package is `install-guide.md`.

A client team runs Ops AI on its own Linux machines with Docker, often with no internet access from those machines, and
its DBA applies every schema change. The release package carries everything that needs: prebuilt images, compose files,
an env template, the database scripts and the guide. Nothing in it needs this repository.

## Make one

```
make release-package TAG=<tag or commit>          # IMAGE_PREFIX=<registry>/<org>/ops-ai to rename the images
```

| Output under `dist/` | What it holds |
|---|---|
| `ops-ai-<version>/` | `INSTALL.md` (from `install-guide.md`), `compose/app.yaml`, `dba.yaml`, `try.yaml`, `ops-ai.env.example` with the image names filled in, `db/postgres/` (`make db-ddl`'s baseline plus a README), `db/azure-sql/` (`make db-ddl DIALECT=mssql` plus a status README), `images.txt` (name, id, platform, size), `release.txt`, `SHA256SUMS` |
| `ops-ai-<version>.tar.gz` | The folder as one file |
| `ops-ai-<version>-images.tar.gz` | Every image for linux/amd64 as `docker save` writes them; `docker load -i` reads it |
| `ops-ai-<version>.SHA256SUMS` | Both tarballs' checksums |

The version is the tag when TAG is one, else the commit's short sha. Everything is built from `git archive TAG`, so
uncommitted files never reach a package. The image builds start a throwaway PostgreSQL 17 for the schema tool and
remove it. `BUILD=0` reassembles from images already built from the same commit (each image's revision label is
checked).

## Prove one

```
make release-proof PACKAGE=dist/ops-ai-<version>.tar.gz
```

It copies only the two tarballs and the checksum file to a temp folder outside the repo and follows `INSTALL.md`:
checksums, `docker load` after removing this machine's copies, a PostgreSQL 17 with TLS whose admin has the attributes
of an Azure Database for PostgreSQL 16+ server admin (not a superuser: CREATEDB, CREATEROLE, BYPASSRLS), the DBA steps
with psql, the env from the template, `docker compose up` as project `ops-release-proof` on :18990 with the fake model,
`deploy/fly/smoke.mjs`, then `stg_click_walk.mjs` over every console page. It then shows four runtime-login statements
refused, models-service refusing a database without its schema, `db/azure-sql` equal to the golden files at the commit,
and a backup restored into a new database with every page walked again. It removes what it started; the loaded images
stay.

## Facts that shape it

| Fact | Consequence |
|---|---|
| Azure's PostgreSQL server admin is not a superuser; only a role holding BYPASSRLS may create one, and Azure gives its admin that on PostgreSQL 16 and newer | The guide requires PostgreSQL 16+ on Azure. On 15 and older, `roles.sql` stops at `ops_runtime_system` |
| `CREATE DATABASE ... OWNER ops_migrator` needs the admin to be able to SET ROLE to it | The DBA runs `GRANT ops_migrator TO <admin>` first |
| The tables with tenant policies are FORCEd, so the owner meets row-level security | `pg_dump` as `ops_migrator` fails; back up as the server admin (BYPASSRLS and a member of `ops_migrator`) |
| A `docker save` bundle has no registry digest | `images.txt` records each image id, which `docker load` keeps; a digest exists once the images are pushed |
| The services take `?ssl=require` in their DSNs | Proven against the TLS server above |

## Push the images to a registry

Not done: a push publishes. The names are `<IMAGE_PREFIX>/<service>:<version>`, by default
`ghcr.io/chanl-ai/ops-ai/<service>`, which nested-path registries (GHCR, Azure Container Registry, Harbor) accept.
Docker Hub takes one path level, so it needs `IMAGE_PREFIX=docker.io/<org>` and names like `<org>/platform`. A push
needs the owner's approval, a login with write access (`docker login ghcr.io` with a token holding `write:packages`),
`docker push` of the ten names in `images.txt`, and a decision on each package's visibility. A client can instead load
the bundle and push it to their own registry, then set `OPS_IMAGE_PREFIX` in the env file.

## Not covered

| Item | State |
|---|---|
| Upgrade from one package to the next | No earlier package exists. `make db-upgrade-sql FROM=<running> TO=<new>` writes the upgrade (`database.md`); the next release adds it to `db/postgres/` |
| Azure SQL and SQL Server | Scripts for review only: never applied to a server (c-345); the services do not run on SQL Server (c-337) |
| A provider key for a real model | The proof connects the fake model only; a key is stored in Settings > Secrets and named with `connect_model.py --key-ref` (`compose.md`, "Connect a model") |
| Image signing, an SBOM per image, arm64 images | Not built |
| The sign-in screens name the demo bank | `components/auth/auth-form-wrapper.tsx`, `login-form.tsx` and `signup/page.tsx` write "Northfield Bank" and "Northfield Ops AI" into the console, so every install shows them; the brand needs to come from a setting |
| A real Azure Database for PostgreSQL server | The proof stands in for it with the admin's documented attributes; not yet run against one |
