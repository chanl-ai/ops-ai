# Ops AI on Kubernetes

Status: current. Proven on a local kind cluster; not yet run on a bank's cluster.

<!-- Built by c-268; the proof is deploy/k8s/proof.sh. -->

Ops AI on Kubernetes uses Kustomize and no other tool: a base with one folder per service, and an overlay per
environment that picks the images, the origin, the secrets and the database. The images are the ones Compose runs,
and the database is installed the way [the database guide](database.md) describes.

The manifests are in `deploy/k8s/`, applied with `kubectl apply -k`; the images build from `deploy/fly/Dockerfile`.

## What runs

| Workload | Image | Probes (startup, readiness, liveness) | Reads |
|---|---|---|---|
| platform, tools, models, kb, files, documents | that service's | its health path, each | `ops-settings`, `ops-origin`, its own Secret `ops-<service>` |
| agents | agents | port open; `/health` (503 until a model is connected, which keeps it out of the Service); port open | as above |
| runner | runner | `/health`, each | `ops-settings`, `ops-origin`, `ops-runner` (no database login); 1 GiB; wasmtime's compiled cache at `/tmp/wasmtime` (`OPS_RUNNER_COMPILED_DIR`) |
| worker | agents, `python -m ops_agents.api.worker` | liveness: a database query | `ops-agents` |
| opa | opa (policy built in) | `/health` | nothing |
| console | console | `/login` | `ops-console` (the service URLs it writes in at start) |
| proxy | proxy (Caddy) | `/api/platform/v1/health` | upstreams by Service name |
| migrate (Job) | platform, `migrate` | none | `ops-settings`, `ops-origin`, `ops-migrate` |

Every pod runs as uid 10001 (`runAsNonRoot`) under the runtime's default seccomp profile, drops every capability,
cannot escalate, and has a read-only root filesystem with an emptyDir at `/tmp` (the proxy also at Caddy's `/config`
and `/data`). The console is the one exception to the read-only root: it copies its build into `.next` inside the
image at every start (`deploy/images/console-start.mjs`). files and kb keep their bytes on a 1 GiB
PersistentVolumeClaim each (`fsGroup` 10001 makes it writable) and update with `Recreate`, since the volume is
ReadWriteOnce.

platform's internal port (8711, API-key introspection) is admitted by the NetworkPolicy `platform-internal` from
agents, tools, models, kb, files and documents only; its public port 8710 stays open to every pod. A NetworkPolicy
is enforced only by a network plugin that implements it (Calico, Cilium, and kindnet on kind 0.33, where the proof ran); on a plugin
that does not, 8711 is open to every pod in the cluster, as it is to every container on the compose network.

## Facts that shape it

| Fact | Consequence |
|---|---|
| Each service refuses a schema behind its chain (c-336) | Services started before the migrate Job restart until it has run; nothing races the migrations |
| A Job's pod template cannot change | An upgrade deletes the finished Job, then applies again (below) |
| Each Secret holds one service's login, its signing key, the public keys and only the keys it uses (`deploy/images/service_keys.py`) | No pod can sign as another service or read another's database tables |
| Secrets come from env files beside the overlay, written by `deploy/k8s/write_secrets.py` and ignored by git | Nothing secret is committed; Kustomize's hash suffix rolls the pods whose Secret changed |
| PostgreSQL is outside the cluster | The base's Service `postgres` has no selector; the overlay's EndpointSlice says where it is (or patch it to `type: ExternalName` for a host name) |
| Pods drop every capability, and a binary carrying a file capability will not start then | The proxy image strips Caddy's (it listens on 8080, no low port) |
| The base's manifests are written by `deploy/k8s/generate.py`, the shared settings read from compose's `x-settings` | Change the table there (or the setting in `deploy/compose/app.yaml`) and regenerate; the YAML is committed for review, and `make verify` runs `generate.py --check`, which fails on a base that is not what it writes |

## Install

1. Install the database as a DBA would (`docs/deploy/database.md`): `roles.sql`, the database owned by
   `ops_migrator`, `bundle.sql`, `grants.sql`, a password per login. Keep the logins in a private file as
   `ops_migrator=...` and `ops_<service>_runtime=...` lines.
2. Copy `deploy/k8s/overlays/example` to your overlay and set every `<...>`: the registry and release tag, the origin
   people open, and the database's address in `postgres-endpoint.yaml`.
3. Write the secret env files beside it:

```
uv run python deploy/k8s/write_secrets.py --overlay deploy/k8s/overlays/<yours> --db-host postgres:5432 --db-name ops \
  --logins <logins file> --admin <file with the five OPS_BOOTSTRAP_* lines>
kubectl apply -k deploy/k8s/overlays/<yours>
kubectl -n ops-ai wait --for=condition=complete job/migrate --timeout=300s
```

4. Connect a model from agents-service (it signs with its own key), put the two printed keys in a private file as
   `OPS_MODELS_KEY_AGENTS=` and `OPS_MODELS_KEY_DOCUMENTS=` lines, write the env files again with `--models <file>`,
   and apply again:

```
kubectl -n ops-ai exec deploy/agents -- python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
  --base-url <endpoint>/v1 --key-ref <secret name> --alias default --model <id> --input-price <n> --output-price <n> \
  --budget <cap> --key-id purpose:agents        # again with --key-id purpose:documents
```

5. Point the bank's ingress or load balancer at the Service `proxy` (port 8080), and walk it:
   `OPS_SMOKE_EMAIL=<admin> OPS_SMOKE_PASSWORD=<password> node deploy/fly/smoke.mjs https://<ops host>`.

## Operate

| Task | How |
|---|---|
| Status | `kubectl -n ops-ai get pods`; a pod's probes in `kubectl describe pod` |
| Logs | `kubectl -n ops-ai logs deploy/<service> -f`; the Job's with `logs job/migrate` |
| Upgrade | Database first (`upgrade.sql` and `grants.sql`, or let the Job migrate with the migrator's login), then set the new tag in the overlay, `kubectl -n ops-ai delete job migrate`, `kubectl apply -k <overlay>` |
| Roll back | Restore the database or run `downgrade.sql`, then the previous tag; a service of an older release refuses a newer schema |
| Back up | The database as any PostgreSQL; the files and kb PersistentVolumeClaims with the cluster's volume snapshots |
| Remove | `kubectl delete -k <overlay>` (the claims go with it) |

## Proof

`sh deploy/k8s/proof.sh` (kind and kubectl on the machine, about 3 GB of Docker memory): builds the images, makes
cluster `ops-ai-proof` with the proxy's NodePort on `localhost:18891`, starts a PostgreSQL container outside the
cluster and installs the baseline there with one login per service, writes the Secrets, applies the kind overlay,
waits for the Job and every Deployment, connects the fake model, prints each pod's uid, read-only root and seccomp
profile, checks that tools reaches platform's internal port and the worker is refused, and runs the smoke walk:
sign-in, chat, an upload, a workflow run on the worker, a document read and three console pages. It removes the
cluster and the database at the end (`KEEP=1` leaves them).

## Not covered

| Item | State |
|---|---|
| A Helm chart | Not built: Kustomize overlays carry the same choices |
| Ingress and TLS | The bank's own, in front of the Service `proxy` |
| More than one replica, autoscaling, disruption budgets | One replica each; the services are stateless apart from files and kb |
| The embed app | No image yet |
| A cloud cluster | Proven on kind only |
