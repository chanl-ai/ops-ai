# Monitor

Status: current. Health checks and logs are built; metrics are planned.

Know whether an install is healthy and find out why when it is not. Every container has a health check, every service
writes structured logs to standard output for your collector, and a few signals tell you when people or workers are
falling behind.

## Check the install

```bash
./install.sh status
```

It prints the version, image source, database and model, each container's state, then runs the install check: health
through the published port, the sign-in page, a sign-in as the first admin, and one read from every service.

| Check | Compose | Kubernetes | Healthy |
|---|---|---|---|
| Every container | `$C ps` | `kubectl -n ops-ai get pods` | Each service healthy or ready; the schema job exited 0 |
| The entry point | `curl -fsS https://<your host>/api/platform/v1/health` | Same | `{"status":"ok"}` |
| Sign-in | Open your address and sign in | Same | The console opens |

Here `$C` is your Compose command, for example `docker compose -p ops-ai -f deploy/compose/app.yaml --env-file
ops-ai.env`.

| Container | Unhealthy means |
|---|---|
| agents | The database is unreachable, or no model is connected: it answers 503 until one is |
| tools | The policy engine does not serve the gateway's own policy: it answers 503 `policy_drift` |
| worker | The database is unreachable |
| any other service | The process is down |
| proxy | It cannot reach the platform service |

## Read the logs

| Task | Script | Compose | Kubernetes |
|---|---|---|---|
| One service | `./install.sh logs agents` | `$C logs -f agents` | `kubectl -n ops-ai logs deploy/agents -f` |
| Every service | `./install.sh logs` | `$C logs --since 1h` | `kubectl -n ops-ai logs deploy/<service> --since 1h` |
| The schema job | `./install.sh logs migrate` | `$C logs migrate` | `kubectl -n ops-ai logs job/migrate` |

Each line is one JSON object with the time, level, event, service, and the request, tenant and team ids. Secret values
are masked before the line is written.

## What to watch

| Signal | Why it matters | Healthy |
|---|---|---|
| The work queue | Runs waiting to be claimed mean the workers are busy or down | Claimed within a second or two |
| Crashed and recovered runs | Each crash runs a step and its model calls again | Rare, each followed by a recovery |
| Tool calls left running | The gateway stopped mid-write, so the effect on your system is unknown | None; each needs a person to check the system it called |
| Overdue human tasks | People are not keeping up with the queue | Within the deadlines your workflows set |
| Model spend against budgets | A spent key stops new work | Below each key's cap |
| Database size and write load | Saved run state grows with open work | Steady; vacuum on a schedule |
| Clock | Leases and timers use the database's clock | Hosts within a few seconds of it |

## Scale

| Part | How it scales |
|---|---|
| Workflow runs | Add worker processes. Each runs 4 runs at once from the shared queue; a run waiting for a person holds no worker |
| The APIs | Every service except files and knowledge is stateless, so more replicas can run behind the proxy or a Service |
| Files and knowledge | One replica each, since their bytes are on a volume one replica writes |
| Crash recovery | A run's lease expires 15 seconds after its worker stops, and another worker continues from its last saved step |

## Limits

- Metrics and an OpenTelemetry exporter are planned; today the signals above are read from the console and the
  database.
- Per-tenant caps on running runs, so one tenant cannot starve another, are planned.
