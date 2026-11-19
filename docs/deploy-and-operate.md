# Deploy and operate

Status: current. Version 1.0.0 is the current release.

Run Ops AI on your own infrastructure and keep it healthy. These pages are for the operator who installs and runs Ops
AI for a team, and the DBA who looks after its database; each one is a task with the commands you type.

Ops AI is self-hosted today: your team runs it on Docker Compose or Kubernetes, its data stays in your PostgreSQL and
file store, and you choose when to upgrade. A hosted service is planned.

## Install

<!-- site: cards -->
1. **[Choose a deployment](guide/deployment-options.md)**: One machine or a cluster, online or offline, the network and sizing.
2. **[Install with the script](deploy/install.md)**: One command on a Linux machine with Docker, checked when it finishes.
3. **[Docker Compose](deploy/compose.md)**: Every step by hand on one machine.
4. **[Kubernetes](deploy/kubernetes.md)**: A Kustomize overlay for your cluster.
5. **[Release package](deploy/release-package.md)**: Install on machines with no internet access.
6. **[Database](deploy/database.md)**: Your DBA applies the schema from reviewed scripts.

## Operate

<!-- site: cards -->
- **[Monitor](deploy/monitoring.md)**: Health checks, logs, what to watch and how to scale.
- **[Upgrade](deploy/upgrade.md)**: Move to a new release and roll back.
- **[Back up and restore](deploy/backup-and-restore.md)**: The database, the stored files and the keys.
- **[Security scanning](deploy/security-scanning.md)**: Verify a release's signature and see what each release is scanned for.

## Next

<!-- site: cards -->
- **[What runs](guide/system-components.md)**: Each container, what it stores and what it calls.
- **[Security](security.md)**: How teams, data and model calls are kept under control, for a security review.
