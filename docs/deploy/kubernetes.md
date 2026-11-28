# Install on Kubernetes

Status: current. Proven on a local kind cluster; not yet run on a managed cloud cluster.

Run Ops AI on your Kubernetes cluster when your platform team runs workloads there rather than on single machines. The
install is plain Kustomize: a base with one folder per service, and an overlay you copy for your environment. The images
are the ones Compose runs, and PostgreSQL stays outside the cluster.

## Before you start

| Item | What you need |
|---|---|
| A cluster | `kubectl` with Kustomize, a namespace you may create, and a network plugin that enforces NetworkPolicy (Calico, Cilium or similar) |
| The manifests | A clone at the release tag: `git clone --branch v1.0.0 https://github.com/chanl-ai/ops-ai.git` |
| PostgreSQL | 15 or newer, installed by your DBA with one login per service ([Database](database.md)) |
| A model endpoint | Any OpenAI-compatible endpoint and its key |
| Python with uv | On the machine you install from, to write the Secrets |

## Install

<!-- site: steps -->
1. **Install the database** with your DBA ([Database](database.md)), and keep the logins in a private file as
   `ops_migrator=...` and `ops_<service>_runtime=...` lines.
2. **Copy the example overlay** and set every `<...>` in it: the registry and release tag, the address people open,
   and the database's address in `postgres-endpoint.yaml`.

   ```bash
   cp -r deploy/k8s/overlays/example deploy/k8s/overlays/prod
   ```

3. **Write the Secrets and apply.** The Secret files are written beside the overlay and ignored by git.

   ```bash
   uv run python deploy/k8s/write_secrets.py --overlay deploy/k8s/overlays/prod --db-host postgres:5432 --db-name ops \
     --logins <logins file> --admin <file with the five OPS_BOOTSTRAP_* lines>
   kubectl apply -k deploy/k8s/overlays/prod
   kubectl -n ops-ai wait --for=condition=complete job/migrate --timeout=300s
   ```

4. **Connect a model.** Run the connect step twice, put the two printed keys in a private file as
   `OPS_MODELS_KEY_AGENTS=` and `OPS_MODELS_KEY_DOCUMENTS=` lines, write the Secrets again with `--models <file>`,
   and apply again.

   ```bash
   # Signs in as the first admin; the password is asked for at the terminal, never put on the command line.
   kubectl -n ops-ai exec -it deploy/agents -- python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
     --admin-email <first admin email> --base-url <endpoint>/v1 --key-ref <name of the stored key> --alias default \
     --model <id> --input-price <n> --output-price <n> --budget <cap> --key-id purpose:agents --password-stdin
   # again with purpose:documents
   ```

5. **Route traffic** from your ingress or load balancer, with TLS, to the Service `proxy` on port 8080. Sign in as the
   first admin.

## How it runs

- Every pod runs as a non-root user with every capability dropped, the runtime's default seccomp profile and a
  read-only root filesystem; the console is the one pod with a writable root, because it writes its build at start.
- Each service gets its own Secret holding its own database login and only the keys it uses, so no pod can act as
  another service or read another's tables.
- Services that start before the schema job has run restart until it finishes; nothing races the schema.
- The files and knowledge services keep their bytes on a 1 GiB volume each and run one replica.
- A NetworkPolicy admits only the services to the platform's private API-key port. On a network plugin that does not
  enforce NetworkPolicy, that port is open to every pod in the cluster.

## Options

| Setting | Where | What it does |
|---|---|---|
| Images and tag | The overlay's `kustomization.yaml` | The registry and release to run |
| Origin | The overlay | The address people open |
| Database address | `postgres-endpoint.yaml` | An EndpointSlice for an IP, or patch the Service to `ExternalName` for a host name |
| Volume size | The overlay | Raise the files and knowledge volumes above 1 GiB for real use |
| `OPS_FORMS_TRUSTED_PROXIES` | The overlay | Which pod networks may set the client address for hosted forms; narrow it if the cluster runs workloads you do not trust |
| Plugins | The overlay | Mount a volume holding the plugins folder at `/plugins` in tools and kb; the base mounts none |

## Limits

- One replica of each service; autoscaling and disruption budgets are not set.
- A Helm chart is planned; the Kustomize overlays carry the same choices.
- The app that serves chat widgets on your other sites has no image yet.

## Next

<!-- site: cards -->
- **[Monitor](monitoring.md)**: Pod status, health and logs.
- **[Upgrade](upgrade.md)**: Database first, then the new tag.
- **[Back up and restore](backup-and-restore.md)**: The database and the two volumes.
