# Decision records

Status: current, 2026-11-18. ADR-0017 is decided and ADR-0018 is proposed; ADR-0001 to ADR-0016 are options, several
superseded in part. The choice in force for each area is in [platform choices](../platform-choices.md).

Each record keeps the options considered for one question, their scores and a recommendation. A record is not changed
when the build moves on: its status line says what superseded it, and the current outcome is kept in one place,
[platform choices](../platform-choices.md), so a reader never has to work out the answer from the scoring.

## Records

| Record | Question | Status | Where the current answer is |
|---|---|---|---|
| [ADR-0001](durable-execution-runtime.md) | Durable execution and the workflow runtime | Superseded in part: no Temporal; `ops_engine` on LangGraph and PostgreSQL | [Platform choices: workflow and agent execution](../platform-choices.md#choices-by-area) |
| [ADR-0002](implementation-language.md) | Python, TypeScript or both | Option | Python services, TypeScript console |
| [ADR-0003](workflow-definition-format.md) | Workflow definition format and portability | Option | [Definitions and versions](../definitions-and-versions.md) |
| [ADR-0004](deployment-tenancy-and-promotion.md) | Deployment, tenancy and promotion | Superseded in part: no Temporal; approver rules moved | [Identity and tenancy](../identity-and-tenancy.md), [service map](../service-map.md#deployment-targets) |
| [ADR-0005](identity-and-entitlement.md) | Identity and entitlement of runs | Option; approver rules moved | [Identity and tenancy](../identity-and-tenancy.md), [roles and permissions](../roles-and-permissions.md) |
| [ADR-0006](data-stores-and-evidence.md) | Data stores and evidence | Superseded in part: timers and run history in PostgreSQL; MySQL dropped by ADR-0017 | [Data](../data.md) |
| [ADR-0007](build-vs-adopt.md) | What to build and what to adopt | Superseded in part: LangGraph adopted, Temporal removed | [Platform choices](../platform-choices.md) |
| [ADR-0008](ai-gateway.md) | An AI gateway, and whether it is needed on day one | Option | models-service ([platform choices](../platform-choices.md#choices-by-area)) |
| [ADR-0009](chat-experience.md) | Chat inside the platform | Superseded in part: chat runs on agents-service | [Chat in the console](../../console/chat.md) |
| [ADR-0010](object-storage.md) | Object storage | Option | [files-service](../../services/files-service/overview.md) |
| [ADR-0011](prompt-management.md) | Prompt management | Superseded by ADR-0012: shared text is an always-on skill | [Agent guardrails and skills](../agent-guardrails.md) |
| [ADR-0012](assurance.md) | Governance and testing as one system | Option; approver rules moved | [Roles and permissions](../roles-and-permissions.md#approvals) |
| [ADR-0013](auth-provider-seam.md) | The sign-in provider seam | Option | [Identity and tenancy](../identity-and-tenancy.md), [SAML sign-in](../saml-sign-in.md) |
| [ADR-0014](agent-loop-library.md) | The agent loop library | Option | Pydantic AI ([runtime](../runtime.md)) |
| [ADR-0015](execution-engine-seam.md) | The execution engine seam | Superseded in part: no Temporal adapter | [Workflow runner](../workflow-runner.md) |
| [ADR-0016](fencing-and-timers.md) | Fencing and timers | Superseded in part: fencing by lease generation carries into `ops_engine` | [Durability, failure and audit](../durability-failure-and-audit.md) |
| [ADR-0017](database-support.md) | Which databases Ops AI supports | Decided: PostgreSQL, and SQL Server 2025 or Azure SQL; MySQL dropped | [Data](../data.md), [Azure SQL guide](../../guide/azure-sql.md) |
| [ADR-0018](template-copy-updates.md) | How a template copy takes an update | Proposed | [Templates](../templates.md) |

## How options are scored

The records score each option from 1 to 5 against these weights, set for a regulated bank. The total is the sum of
weight times score, divided by 100.

| Criterion | Weight | A 5 looks like |
|---|---|---|
| Durability and auditability | 13 | A crash at any point resumes from the last completed step with no lost or duplicated side effect |
| Determinism and replay | 8 | Past runs replay from recorded history to test a change |
| Human-in-the-loop waits of hours to days | 13 | A run waits days for a person at no compute cost, with a durable SLA timer |
| Versioning of running instances | 13 | Old runs finish on their version; new runs take the new one |
| Security and isolation | 9 | mTLS, per-tenant authorisation, payload encryption, SSO |
| Operability on-prem or private cloud | 9 | Runs on the bank's infrastructure with documented HA and no call home |
| Licence, vendor risk and cost | 9 | OSI licence, more than one source of support, predictable cost |
| Talent pool | 4 | Hireable in a normal cycle |
| Connector ecosystem | 4 | Large maintained catalogue |
| Fit for event-driven, per-item runs | 4 | A run per email in under a second, thousands concurrent |
| Marginal effort per new workflow | 14 | Workflow N is configuration on a template, published by its owner, with no engine code |
