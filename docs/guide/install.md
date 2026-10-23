# Install

Status: current.

<!-- The steps below are included from docs/deploy/install.md, the install script's guide, when the page and
INSTALL.md are built; edit them there. -->

One script installs Ops AI on a machine with Docker from a clone of the repository, asks a few questions, checks the
result, and later upgrades, backs up, restores and reports on the same install ([Operate](operate.md)). It pulls the
published images by default; a release's offline image file, or a build from source, serves a machine with no
registry access.

The published images are at `ghcr.io/chanl-ai/ops-ai`.

## Before you start

| Item | What you need | Details |
|---|---|---|
| A host | One Linux machine with Docker Engine 24 or newer, Docker Compose 2.22 or newer, curl and tar, 4 GB of memory for the containers and 15 GB of free disk | [Sizing](deployment-options.md#sizing) |
| A DNS name and TLS | A name such as `ops.example.com` on your load balancer or reverse proxy, forwarding to the port the script asks for | [The network](deployment-options.md#the-network) |
| PostgreSQL | For a trial, the script's built-in database. For real use, your own PostgreSQL 15 or newer: either a login that may change the schema, or DBA mode, where your DBA applies the scripts the install writes | [Data and database](data-and-database.md) |
| A model endpoint | Any OpenAI-compatible endpoint and its key; the built-in test model will do for a first look | [Models](models.md) |
| The first admin | A name and email address for the person who signs in first and invites everyone else | |
| Sign-in and outbound hosts | Your identity provider's OIDC or SAML details, and the hosts Ops AI will call, for the Security admin to set after the install | [Security and governance](security-and-governance.md) |

<!-- guide: include from "## Install" until "## Appendix: by hand" -->
The install steps, the questions the script asks and its other commands are in [Install Ops AI with install.sh](../deploy/install.md).

## By hand

Every step the script runs can also be run by hand: the Compose files and settings in
[Ops AI on Docker Compose](../deploy/compose.md), the DBA's scripts in
[The database](../deploy/database.md), and a Kubernetes install in [Ops AI on Kubernetes](../deploy/kubernetes.md).
