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

## Working here

| Task | Command |
|---|---|
| Change a workload, a probe or a shared setting | Edit `generate.py` (or `x-settings` in `deploy/compose/app.yaml`), then `uv run python deploy/k8s/generate.py`; never hand-edit `base/` |
| Checks | `uv run python deploy/k8s/generate.py --check`, `uv run pytest -q deploy/k8s/tests` |
| Prove it on kind | `sh deploy/k8s/proof.sh` (`KEEP=1`, `BUILD=0`) |

Overlay env files written by `write_secrets.py` are git-ignored; never commit one. Folder rules: `../CLAUDE.md`.
