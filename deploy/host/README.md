# Process host

`ops_host.py` runs in the foreground as a machine's main process and starts the processes a TOML file lists, in order.
`OPS_ENABLED_SERVICES` (`all` or names) picks which, so one image runs every service or one per machine. Each process
has its own env with `${VAR}` taken from the host's environment; an unset name stops the host before anything starts.
A process that exits restarts after a backoff; one that exits more than `max_restarts` times in the window stops the
host with exit 1. SIGTERM stops every process group. Standard library only.

Tests: `uv run pytest deploy/host/tests`. Config in use: `deploy/fly/processes.toml`; runbook `docs/deploy/fly-staging.md`.
