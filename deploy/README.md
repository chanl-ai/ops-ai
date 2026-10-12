# Deploy

How to run Ops AI outside a laptop. Every release must run on one virtual machine with no container runtime; Compose
and Kubernetes are optional. Design: `docs/architecture/service-map.md` ("Deployment targets").

| Folder | State |
|---|---|
| `compose/` | Local dev dependencies (PostgreSQL, OPA) |
| `vm/` | Not started: systemd units for the gateway, tools service and AI gateway, native PostgreSQL |
| `k8s/` | Not started: Kustomize bases per service, overlays per environment |
