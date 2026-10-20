# Kubernetes

Kustomize manifests for Ops AI from the same images as compose and Fly: a base with one folder per service, and an
overlay per environment. Runbook: `docs/deploy/kubernetes.md`.

| Path | Role |
|---|---|
| `base/` | Written by `generate.py` (`--check` fails when it is stale): a Deployment (and Service) per workload with probes, uid 10001 and a read-only root, platform's NetworkPolicy, the settings ConfigMap read from compose's `x-settings`, the migrate Job, the outside-Postgres Service, the namespace |
| `overlays/example/` | A bank's template: registry images, its origin, its database address, the per-service Secrets |
| `overlays/kind/` | The local proof's overlay: loaded images, a NodePort on localhost:18891, the fake model |
| `write_secrets.py` | Writes an overlay's git-ignored env files, one per service plus the migrate Job's |
| `proof.sh` | The whole install on a local kind cluster with an outside PostgreSQL, then the smoke walk |
