# Install on Kubernetes

Status: current. Proven on a local kind cluster, and not yet run on a managed cloud cluster.

When your platform team runs workloads on a cluster rather than on single machines, an install built around one
machine's Docker does not fit. It cannot use your ingress, your Secrets or your pod policies. The Kubernetes install is
plain Kustomize, so your team can read, patch and review everything that gets applied. It has a base with one folder per
service, and an overlay you copy for each environment. The images are the ones Compose runs, and PostgreSQL stays
outside the cluster.

## What you need before you start

| Item | What you need |
|---|---|
| A cluster | `kubectl` with Kustomize, a namespace you may create, and a network plugin that enforces NetworkPolicy (Calico, Cilium or similar) |
| The manifests | A clone at the release tag: `git clone --branch v1.2.0 https://github.com/chanl-ai/ops-ai.git` |
| PostgreSQL | 15 or newer with the `vector` extension, installed by your DBA with one login per service ([Database](database.md)) |
| A model endpoint | Any OpenAI-compatible endpoint and its key |
| Python with `uv` | On the machine you install from, to write the Secrets |

## Install on your cluster

<!-- site: steps -->
1. **Install the database** with your DBA ([Database](database.md)). Keep the logins in a private file as
   `ops_migrator=...` and `ops_<service>_runtime=...` lines, one for the migrator and one for each of the seven
   services.
2. **Copy the example overlay** and set every `<...>` in it: the registry and the release tag, the address people open,
   and the database's address in `postgres-endpoint.yaml`. The registry images are tagged `1.2.0`, without the `v`.

   ```bash
   cp -r deploy/k8s/overlays/example deploy/k8s/overlays/prod
   ```

3. **Write the Secrets and apply.** The script writes the Secret files beside the overlay, and git ignores them. The
   admin file holds five lines: `OPS_BOOTSTRAP_TENANT_NAME`, `OPS_BOOTSTRAP_TEAM_NAME`, `OPS_BOOTSTRAP_ADMIN_EMAIL`,
   `OPS_BOOTSTRAP_ADMIN_NAME` and `OPS_BOOTSTRAP_ADMIN_PASSWORD`.

   ```bash
   uv run python deploy/k8s/write_secrets.py --overlay deploy/k8s/overlays/prod --db-host postgres:5432 --db-name ops \
     --logins <logins file> --admin <admin file>
   kubectl apply -k deploy/k8s/overlays/prod
   kubectl -n ops-ai wait --for=condition=complete job/migrate --timeout=300s
   ```

4. **Connect a model.** Run the connect step twice, once for each key id. Put the two printed keys in a private file as
   `OPS_MODELS_KEY_AGENTS=` and `OPS_MODELS_KEY_DOCUMENTS=` lines, write the Secrets again with `--models <file>`, and
   apply again.

   ```bash
   kubectl -n ops-ai exec deploy/agents -- python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
     --base-url <endpoint>/v1 --key-ref <name of the stored key> --alias default --model <id> \
     --input-price <n> --output-price <n> --budget <cap> --key-id purpose:agents   # again with purpose:documents
   ```

   Save the provider's key in the console, under Settings › Models › Connections, with the name you gave `--key-ref`.

5. **Route traffic** from your ingress or load balancer, with TLS, to the Service `proxy` on port 8080. Sign in as the
   first admin.

## What success looks like

`kubectl -n ops-ai get pods` lists every workload as ready, and the `migrate` job as complete. The proxy answers at
`/api/platform/v1/health`, and the first admin signs in at your address. Until step 4 is done, the agents pod stays
unready, because its health check fails until a model is connected.

## How it runs

- Every pod runs as a non-root user with every capability dropped, the runtime's default seccomp profile and a read-only
  root filesystem. The console is the one pod with a writable root, because it writes its build at start.
- Each service gets its own Secret holding its own database login and only the keys it uses, so no pod can act as
  another service or read another's tables.
- A service that starts before the schema job has finished restarts until it has, so the two cannot race.
- The files and knowledge services keep their bytes on a 1 GiB volume each, and run one replica.
- A NetworkPolicy lets only the services that need it reach the platform's private API-key port. On a network plugin that
  does not enforce NetworkPolicy, that port is open to every pod in the cluster.

## Settings you will change

| Setting | Where | What it does |
|---|---|---|
| Images and tag | The overlay's `kustomization.yaml` | The registry and release to run |
| Origin | The overlay | The address people open |
| Database address | `postgres-endpoint.yaml` | An EndpointSlice for an IP address. For a host name, patch the Service to `ExternalName` and delete the file |
| Volume size | The overlay | Raise the files and knowledge volumes above 1 GiB for real use |
| `OPS_FORMS_TRUSTED_PROXIES` | The overlay | Which pod networks may set the client address for hosted forms. The base trusts the private ranges `10.0.0.0/8` and `172.16.0.0/12`, so narrow it if the cluster runs workloads you do not trust |
| Plugins | The overlay | Mount a volume holding the plugins folder at `/plugins` in the tools and knowledge pods. The base mounts none |
| Feature flags | `OPS_FLAGS` in the overlay | The features turned on ([Feature flags](install.md#turn-on-a-feature-flag)) |

## Limits

- Each service runs one replica. Autoscaling and disruption budgets are not set.
- Resource requests are 50m CPU and 256 MiB of memory per pod, with 512 MiB for the agents, worker, documents and console
  pods, 1 GiB for the code-tools runner and 128 MiB for the proxy. Memory limits equal the requests, and no CPU limit is
  set.
- A Helm chart is planned. The Kustomize overlays carry the same choices.
- The app that serves chat widgets on your other sites has no image yet.
- Search by meaning needs a third model key and an embedding alias ([Set the embedding model](install.md#set-the-embedding-model)).
  `write_secrets.py --models` accepts an `OPS_MODELS_KEY_KB` line for it.

## Next

<!-- site: cards -->
- **[Monitor](monitoring.md)**: Pod status, health and logs.
- **[Upgrade](upgrade.md)**: Database first, then the new tag.
- **[Back up and restore](backup-and-restore.md)**: The database and the two volumes.
