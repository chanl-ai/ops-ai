# Ops AI architecture and installation guide

Status: current.

<!-- The one source of the client guide: scripts/docs/build_guide.mjs renders these files into
docs/deploy/client-install-guide.html, and the install and operate sections into the release package's INSTALL.md.
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
| Partial | Azure SQL: scripts ready for review, services not yet |
| In progress | Team isolation inside the database: in progress |

## Contents

1. [Overview](overview.md): what Ops AI does, for whom, and the platform in one picture
2. [System components](system-components.md): every container, its port, what it stores and what it calls
3. [How work flows](how-work-flows.md): a chat turn with an approval, a workflow with a human task, and an email that becomes a case
4. [Data and database](data-and-database.md): the entities, what each service stores, tenants and teams, files, retention and audit
5. [Security and governance](security-and-governance.md): sign-in, roles, approvals, the tool gateway, secrets, masking and audit
6. [Models](models.md): the AI gateway, aliases, budgets, data sensitivity and the test model
7. [Deployment options](deployment-options.md): one VM with Docker Compose, Kubernetes, tenancy, the network and sizing
8. [Install](install.md): the install script
9. [Operate](operate.md): health, logs, upgrade and roll back, back up and restore, scaling
10. [Azure SQL](azure-sql.md): what is ready for review and what is still to come
11. [What's built today](whats-built-today.md): built, partial or planned, capability by capability
12. [Support](support.md): who to contact
