# Install

Status: current.

<!-- The steps below are included from docs/deploy/install.md, the install script's guide, when the page and
INSTALL.md are built; edit them there. -->

Before you run the first command, you need six things ready: a machine, a DNS name, a database, a model, a first admin
and your sign-in details. This page lists what to have in hand, then points to the way that fits your setup. On
one machine, the install script does every step and checks the result. On a cluster, or when you run each step
yourself, the same images start from Compose or Kubernetes files. Version 1.2.0 is the current release, and its images
are published at `ghcr.io/chanl-ai/ops-ai`.

> [!NOTE]
> To try Ops AI on a laptop rather than install it for a team, use the [Quickstart](quickstart.md). It runs from a
> clone with a test model and a sample team.

## What to have ready

| Item | What you need | Details |
|---|---|---|
| A host | One Linux machine with Docker Engine 24 or newer, Docker Compose 2.22 or newer, `curl` and `tar`, 4 GB of memory for the containers and 15 GB of free disk | [Sizing](deployment-options.md#sizing) |
| A DNS name and TLS | A name such as `ops.example.com` on your load balancer or reverse proxy, forwarding to the port the script asks for | [The network](deployment-options.md#the-network) |
| PostgreSQL | For a trial, the script's built-in database. For real use, your own PostgreSQL 15 or newer with the `vector` extension: either a login that may change the schema, or DBA mode, where your DBA applies the scripts the install writes | [Data and database](data-and-database.md) |
| A model endpoint | Any OpenAI-compatible endpoint and its key. The built-in test model will do for a first look | [Models](models.md) |
| The first admin | A name and email address for the person who signs in first and invites everyone else | |
| Sign-in and outbound hosts | Your identity provider's OIDC or SAML details, and the hosts Ops AI will call, for the Security admin to set after the install | [Security and governance](security-and-governance.md) |

<!-- guide: include from "## Run the install script" until "## Doing each step yourself" -->
The commands, the questions the script asks and its other commands are in [Install with the script](../deploy/install.md).

## Other ways to install

| Way | Use it when |
|---|---|
| [Docker Compose by hand](../deploy/compose.md) | You run each step yourself on one machine. The DBA's scripts are in [Database](../deploy/database.md) |
| [Kubernetes](../deploy/kubernetes.md) | Your platform team runs a cluster |
| [Release package](../deploy/release-package.md) | The machines have no internet access |

## The command line on its own

To script Ops AI from a machine that does not run it, install only the `opsai` command, including behind a company
package mirror or with no network: [Install the command line](install-cli.md).
