# Deploy and operate

Status: current.

Run Ops AI on your own machines and keep it healthy: pick a layout, install it, set up its database, then upgrade,
back up and watch it. The pages in this tab are for the operator who installs and runs Ops AI for a team, so they name
the commands and settings you type.

## Where to start

<!-- site: cards -->
1. **[Choose a deployment](guide/deployment-options.md)**: Docker Compose on one machine or Kubernetes, single or many tenants, the network and sizing.
2. **[Install](guide/install.md)**: The install script, step by step, with Compose, Kubernetes and the release package.
3. **[Database](deploy/database.md)**: Install, upgrade and verify the database from reviewed scripts, on PostgreSQL or SQL Server.
4. **[Upgrade, back up and monitor](guide/operate.md)**: Health, logs, upgrades and rollback, backup and restore, scaling and key rotation.

## Hosted and self-hosted

| | Self-hosted | Hosted |
|---|---|---|
| Who runs it | Your team, on Compose or Kubernetes | planned |
| Where data is kept | Your database and file store | planned |
| Upgrades | You run them, from a release package | planned |

## Next

<!-- site: cards -->
- **[What runs](guide/system-components.md)**: Each part of an install, what it stores and what it calls.
- **[Security scanning](deploy/security-scanning.md)**: The checks each release passes and how to verify a signed release.
- **[Security](security.md)**: How teams, data and model calls are kept under control, for a security review.
