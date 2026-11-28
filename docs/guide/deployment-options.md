# Choose a deployment

Status: current.

Before anyone installs Ops AI, your team has to decide where it runs. An architecture review asks the same
questions each time: one machine or a cluster, whether the machines can reach the internet, how many organisations share
an install, which ports open, and how big the database must be. This page answers them. The same images run in every
layout. What changes is how they start, how secrets reach them and where file bytes are kept. PostgreSQL is always yours
and runs outside the containers. The Compose and Kubernetes layouts have both passed the release's install tests, and the
sizing figures are a starting point to measure your own workload against.

Settle it before you install, because the layout decides how secrets reach the containers and where file bytes live. Start
with the choice below, then read the network and sizing sections for what your platform team needs to approve.

<!-- site: decision caption="Which install to use, by what your machines can reach and who runs them" -->
- **Can the machines reach the internet?**
  - **No**: [Install offline from a release package](../deploy/release-package.md).
  - **Yes**:
    - **Does your platform team run a Kubernetes cluster for this?**
      - **Yes**: [Install on Kubernetes](../deploy/kubernetes.md).
      - **No**:
        - **Do you want to run each step yourself?**
          - **Yes**: [Install with Docker Compose](../deploy/compose.md).
          - **No**: [Install with the script](../deploy/install.md).

## Where it can run

| Option | Use it when | Status |
|---|---|---|
| [The install script](../deploy/install.md) | One Linux machine with Docker. The script installs, checks, upgrades, backs up and restores. A second machine with the same install is a standby you restore a backup onto | Built: proven on a CI runner and on one machine, not yet on a client's server |
| [Docker Compose by hand](../deploy/compose.md) | One machine, where you run each step yourself | Built: proven on one machine |
| [Kubernetes](../deploy/kubernetes.md) | Your platform team runs a cluster. Plain Kustomize: a base and an overlay per environment | Built: proven on a local kind cluster, not yet on a managed cloud cluster |
| [Release package](../deploy/release-package.md) | The machines have no internet access | Built: proven on a machine holding only the package |
| A Helm chart | | Planned: the Kustomize overlays carry the same choices |
| One VM with no container runtime | | Planned |

## Single-tenant and multi-tenant

| Choice | What it means | Status |
|---|---|---|
| One installation per organisation | The install creates one tenant, its Security team and the first admin. Departments are teams inside it, and the team is the data boundary between them | Built: the recommended shape |
| Several organisations in one installation | Every row carries its tenant, and the agents and platform tables enforce it in the database. Creating a second tenant, per-tenant model aliases and keys, and tenant policies in the database for every service are still to come | Planned |

## The network

<!-- diagram: network-map -->
```mermaid
flowchart TB
  U["Staff browsers"]:::outside --> LB["Your TLS terminator or load balancer, 443"]:::outside
  subgraph VM["Ops AI host or cluster"]
    direction TB
    PX["proxy: OPS_PUBLIC_PORT, 8890 by default"]
    SVC["services, worker, console, policy engine<br/>on a private network"]
    PX --> SVC
  end
  LB --> PX
  SVC --> PG[("PostgreSQL<br/>5432")]:::store
  SVC --> SYS["Your systems<br/>HTTPS, allow-listed"]:::outside
  SVC --> MAIL["Mail server<br/>IMAP, SMTP, Graph"]:::outside
  SVC --> IDP["Identity provider<br/>OIDC or SAML"]:::outside
  SVC --> LLM["Model endpoint<br/>HTTPS"]:::outside
  SVC -.-> OBJ[("Object storage<br/>optional")]:::store
```

*Traffic reaches Ops AI through one inbound port, from your TLS terminator. Each outbound connection goes only to a system you configure.*

| Direction | From | To | Port | Why |
|---|---|---|---|---|
| Inbound | Your TLS terminator or load balancer | The proxy | `OPS_PUBLIC_PORT` (8890 by default), plain HTTP inside your network | The console and the APIs, all on one origin |
| Outbound | Ops AI | PostgreSQL | 5432, TLS where the server requires it | All data |
| Outbound | Ops AI | Your model endpoint | 443 | Model calls |
| Outbound | Ops AI | Your systems | 443, hosts on the allow-list only | Tool calls |
| Outbound | Ops AI | Your mail server or mail API | 993 for IMAP, 587 or 465 for SMTP, 443 for Microsoft Graph or Gmail | Team mailboxes and replies |
| Outbound | Ops AI | Your identity provider | 443 | Single sign-on, key discovery |
| Outbound | Ops AI | Your DNS resolvers | 53 | Proving an email domain for single sign-on |
| Outbound | Ops AI | S3 or Azure Blob, when configured | 443 | File bytes |
| Outbound | the host | `ghcr.io` (or your own registry), unless images are loaded from the offline image file | 443 | Install and upgrade only |

The table lists every connection Ops AI makes, and your firewall needs no others. Place your TLS terminator in front of
the proxy, because the containers talk to each other in plain HTTP on the private network.

## Sizing

| Part | Starting point | Notes |
|---|---|---|
| One machine for Compose | 4 vCPUs, 8 GB memory and 60 GB of disk to start. Any current 64-bit Linux on x86-64 or ARM64 with Docker Engine 24 or newer and Compose 2.22 or newer. The install script's preflight wants at least 4 GB of memory for the containers and 15 GB of free disk | In the release's install proof all containers together used about 2 GB of memory at rest. Images take about 1.2 GB of disk |
| PostgreSQL | 15 or newer; on Azure Database for PostgreSQL Flexible Server, 16 or newer. General Purpose, 2 vCores, 8 GB memory, 64 GB storage to start | Database size grows with open work and with history until retention jobs exist. The `vector` extension (pgvector 0.5 or newer) must be available, and no other extension is needed |
| Kubernetes requests | 50m CPU each. Memory is 256 MiB by default, 512 MiB for agents, worker, documents and console, 1 GiB for the code-tools runner and 128 MiB for the proxy. Memory limits equal the requests, and no CPU limit is set | One replica each. The files and knowledge services keep bytes on a 1 GiB ReadWriteOnce volume each, so they run one replica. Raise the size for real use |
| Workflow throughput | Each worker process runs 4 runs at once and polls every half second | Add worker processes to add capacity. A run waiting for a person holds no worker |
| File storage | The size of the documents and attachments you keep, for as long as their retention class says | Move to S3 or Azure Blob for large volumes and WORM retention |

Load figures for many concurrent runs are still to be measured and published. Size against a pilot of your own
workload, and watch the work queue and database load ([What to watch](../deploy/monitoring.md#what-to-watch)).
