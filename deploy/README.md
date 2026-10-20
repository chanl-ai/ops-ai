# Deploy

How to run Ops AI outside a laptop. Every release must run on one virtual machine with no container runtime; Compose
and Kubernetes are optional. Design: `docs/architecture/service-map.md` ("Deployment targets").

| Folder | State |
|---|---|
| `compose/` | `app.yaml`: every service, the worker, the console, OPA and a proxy as containers against an outside PostgreSQL, from prebuilt images; `build.yaml` builds them from a checkout; `dba.yaml` for a schema the DBA applied (runbook `docs/deploy/compose.md`); `compose.yaml`: local dev dependencies (PostgreSQL, OPA) |
| `database/` | The schema as reviewed scripts for a DBA: baseline, upgrades, drift, least-privilege roles (runbook `docs/deploy/database.md`) |
| `release/` | The package a client team installs from: images for linux/amd64 as one bundle, compose files, env template, PostgreSQL and Azure SQL scripts, install guide (runbook `docs/deploy/release-package.md`) |
| `images/` | What every image runs at start: the entrypoint, the migration script compose and Fly share, the health check and the console's start (stages in `fly/Dockerfile`) |
| `host/` | The process host: starts the processes `OPS_ENABLED_SERVICES` names from a config file, restarts one that exits, stops them together |
| `fly/` | Staging on one Fly machine: the Dockerfile with every image's stage, proxy, processes, release command, keys, model connection and the smoke walk any install can run. Runbook: `docs/deploy/fly-staging.md` |
| `vm/` | Not started: systemd units for the gateway, tools service and AI gateway, native PostgreSQL |
| `k8s/` | Kustomize: a base per service and an overlay per environment, from the same images, against an outside PostgreSQL (runbook `docs/deploy/kubernetes.md`) |
