# Monitor an Ops AI install

Status: current.

An install can look fine from the outside while a worker is down or a queue is growing, and the first sign is often a
person asking why their approval never arrived. This page shows how to check that an install is healthy, how to find
out why it is not, and which few signals tell you that people or workers are falling behind. Every container has a
health check, and every service writes structured logs to standard output for your log collector.

## Check the install

Run the status command on the machine where you installed:

```bash
./install.sh status
```

It prints the version, the image source, the database and the model, and the state of each container. It then runs the
install check, which tests health through the published port, the sign-in page, a sign-in as the first admin and one
read from every service.

If you installed by hand, check the same things yourself. In the table, `$C` is your Compose command, for example
`docker compose -p ops-ai -f deploy/compose/app.yaml --env-file ops-ai.env`.

| Check | Compose | Kubernetes | Healthy |
|---|---|---|---|
| Every container | `$C ps` | `kubectl -n ops-ai get pods` | Each service is healthy or ready, and the schema job exited 0 |
| The entry point | `curl -fsS https://<your host>/api/platform/v1/health` | The same | `{"status":"ok"}` |
| Sign-in | Open your address and sign in | The same | The console opens |

When a container is unhealthy, this table says where to look first:

| Container | What unhealthy means |
|---|---|
| agents | The database is unreachable, or no model is connected. It answers 503 until one is |
| tools | The policy engine does not serve the gateway's own policy, and the service answers 503 `policy_drift` |
| worker | The database is unreachable |
| Any other service | The process is down |
| proxy | It cannot reach the platform service |

## Read the logs

| Task | Script | Compose | Kubernetes |
|---|---|---|---|
| One service | `./install.sh logs agents` | `$C logs -f agents` | `kubectl -n ops-ai logs deploy/agents -f` |
| Every service | `./install.sh logs` | `$C logs --since 1h` | `kubectl -n ops-ai logs deploy/<service> --since 1h` |
| The schema job | `./install.sh logs migrate` | `$C logs migrate` | `kubectl -n ops-ai logs job/migrate` |

Each line is one JSON object with the time, level, event and service, plus the request, tenant and team ids. Secret
values are masked before the line is written.

## What to watch

Metrics are not built yet, so you read these signals from the console and the database. Check them on a schedule, or
when someone reports that work is slow.

| Signal | Why it matters | Healthy |
|---|---|---|
| The work queue | Runs that wait to be claimed mean the workers are busy or down | Claimed within a second or two |
| Crashed and recovered runs | Each crash runs a step and its model calls again | Rare, and each followed by a recovery |
| Tool calls left running | The gateway stopped in the middle of a write, so the effect on your system is unknown | None. Each one needs a person to check the system it called |
| Overdue human tasks | People are not keeping up with the queue | Within the deadlines your workflows set |
| Model spend against budgets | A spent key stops new work | Below each key's cap |
| Database size and write load | Saved run state grows with open work | Steady, with vacuum on a schedule |
| Clock | Leases and timers use the database's clock | Hosts within a few seconds of it |

## Add capacity

| Part | How it scales |
|---|---|
| Workflow runs | Add worker processes. Each one runs 4 runs at once from the shared queue, and a run that waits for a person holds no worker |
| The APIs | Every service except files and knowledge is stateless, so you can run more replicas behind the proxy or a Service |
| Files and knowledge | One replica each, because their bytes are on a volume that only one replica writes |
| Crash recovery | A run's lease expires 15 seconds after its worker stops, and another worker continues from the last saved step |

## Limits

- Metrics and an OpenTelemetry exporter are planned. Today you read the signals above from the console and the database.
- A per-team cap on concurrent runs exists (`OPS_ENGINE_TEAM_CAP`) and is off by default. A per-tenant cap is planned.
