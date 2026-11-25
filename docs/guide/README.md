# Ops AI architecture and installation guide

Status: current.

<!-- The one source of the client guide: scripts/docs/build_guide.mjs renders these files into
docs/deploy/client-install-guide.html, and the install and operate sections into docs/deploy/install-guide.md. The release package's INSTALL.md is
docs/deploy/package-install.md, written by hand because the package holds no install.sh.
Edit here, then run node scripts/docs/build_guide.mjs. -->

This guide is for the architects, DBAs, security reviewers and operators of a team that runs Ops AI on its own
infrastructure. It says what each part does, how work moves through them, where data is kept and how it is kept apart,
how the platform is secured, how to deploy and run it, and which parts are built today and which are still to come.

Each status in this guide is read from the code of the release it ships with. **Built** means it runs and is tested;
**Partial** means some of it runs and the rest is named; **Planned** means designed and not yet in the code.

## At a glance

| State | What |
|---|---|
| Built | Runs on PostgreSQL 15 or newer |
| Built | Install with one script: `git clone`, then `./install.sh` |
| Built | Docker Compose on Linux (x86-64 or ARM64), or Kubernetes |
| Built | Sign-in with OIDC, SAML or password |
| Partial | SQL Server 2025 and Azure SQL: each service's stores tested on it; a full install not yet proven |
| Partial | Team isolation inside the database: files and documents so far |

## Contents

1. [Overview](overview.md): what Ops AI does, for whom, and the platform in one picture
2. [What runs](system-components.md): every container, what it stores and what it calls
3. [How work flows](how-work-flows.md): a chat turn with an approval, a workflow with a human task, and an email that becomes a case
4. [Build with Ops AI](build-with-ops-ai.md): the example folders in order, and how agents and workflows call each other
5. [Workflows](workflows.md): author, validate, publish and test-run a workflow from the SDK or CLI
6. [Agents](agents.md): author, publish and chat with an agent from the SDK or CLI
7. [The Ops Assistant](ops-assistant.md): the chat checklist, Connect card, Think harder, saving, reused reads and memories
8. [Apps](apps.md): turning an App on, team and personal Accounts, auth configs, Tools, Resources, approvals, a run waiting for a person, and turning an App off
9. [Data and database](data-and-database.md): the entities, what each service stores, tenants and teams, files, retention and audit
10. [Security and governance](security-and-governance.md): sign-in, roles, approvals, the tool gateway, secrets, masking and audit
11. [Models](models.md): the AI gateway, aliases, budgets, data sensitivity and the test model
12. [Choose a deployment](deployment-options.md): one machine with Docker Compose, Kubernetes, offline, tenancy, the network and sizing
13. [Install](install.md): the install script
14. [Install the command line](install-cli.md): the `opsai` command on its own, behind a company mirror or offline
15. [Operate](operate.md): health, logs, upgrade and roll back, back up and restore, scaling, key rotation
16. [Azure SQL](azure-sql.md): what is ready for review and what is still to come
17. [What's built today](whats-built-today.md): built, partial or planned, capability by capability
18. [Support](support.md): who to contact
