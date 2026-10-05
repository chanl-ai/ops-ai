# ADR-0008 AI gateway, and whether it is needed on day one

Status: accepted (draft for review). Formerly DR-8.

## Context

The problem statement mandates that all model traffic goes through one AI gateway that applies bank aliases,
spend limits and redaction, budgets per agent, failover, and makes unregistered agents discoverable
in traffic. Portkey is the preferred alternative to LiteLLM. The first delivery is email
workflows with human approval, agents and knowledge bases, as soon as possible, so the question is
also how much of the gateway has to exist before that.

## Options

| Option | Licence and status | Open source includes | Paid or not in open source | Self-host and data residency |
|---|---|---|---|---|
| **Portkey gateway** | MIT ([repo][portkey-repo]). Gateway 2.0 on 2026-03-24 moved "circuit breaker, semantic cache, budget limits, model catalog, metadata governance, config management" into open source, plus an MCP registry and OAuth 2.1 for MCP ([Gateway 2.0][portkey-2]). Acquired by Palo Alto Networks; closed 2026-05-29 for $140M in cash and replacement awards ([10-Q][panw-10q]) | Routing, retries, fallbacks, load balancing, timeouts, 40+ guardrails, caching, MCP gateway ([repo][portkey-repo]); budgets and rate limits on virtual keys ([summary][portkey-alt], secondary) | The repo README lists PII redaction, semantic caching, access control, advanced logging and prompt management under enterprise ([repo][portkey-repo]); Gateway 2.0 says semantic cache moved to open source, so the README may be stale. The "On-Prem Enterprise Gateway" adds SSO, SCIM, KMS, RBAC, JWT, audit logs and multi-workspace ([Gateway 2.0][portkey-2]). Treat PII redaction as paid until Portkey confirms | Open-source gateway runs on Docker or Kubernetes in the bank. The enterprise hybrid model keeps the gateway and log store in the customer's network while the dashboard and configuration live in Portkey's cloud; "all prompt content and LLM responses remain within your network" ([hybrid][portkey-hybrid]). Fully air-gapped needs an enterprise arrangement ([repo][portkey-repo]) |
| LiteLLM proxy | MIT core with an enterprise folder ([repo][litellm-repo]). PyPI 1.82.7 and 1.82.8 were backdoored on 2026-03-24 after a CI dependency was compromised ([Datadog][litellm-incident], [LiteLLM][litellm-blog]) | Routing, budgets, virtual keys, guardrail hooks, cost tracking | SSO and support ([repo][litellm-repo]) | Self-hosted, Python |
| Kong AI Gateway | Kong Gateway core Apache 2.0 | AI proxy, prompt guard, decorators, templates | AI Sanitizer (PII), semantic guards, advanced rate limiting, audit logging are Enterprise or Konnect ([comparison][kong-ai], secondary) | Self-hosted |
| Envoy AI Gateway ("Agent Router" since 2026-09-10) | Open source; 1.0 on 2026-06-23 ([summary][envoy-aig], secondary) | Multi-provider routing, MCP gateway, token counting, OpenTelemetry GenAI tracing | Redaction and budgets would be our code | Self-hosted on Envoy Gateway |
| Cloud gateways (Azure API Management AI gateway, Amazon Bedrock) | Proprietary | n/a | n/a | Cloud-bound; conflicts with ADR-0004's on-prem requirement. **Not assessed in detail** |
| Build our own proxy | n/a | n/a | Everything | Full control, months of work on commodity routing |

### Criteria and scores

| Criterion | Weight | Portkey OSS | LiteLLM | Kong AI | Envoy AI / Agent Router | Build |
|---|---|---|---|---|---|---|
| Budgets, virtual keys and aliases in the open-source core | 20 | 5 | 5 | 3 | 2 | 3 |
| Redaction and guardrails without a paid tier | 15 | 3 | 3 | 2 | 1 | 2 |
| Runs fully inside the bank, no vendor control plane | 15 | 4 | 5 | 5 | 5 | 5 |
| Supply-chain and vendor-direction risk | 15 | 3 | 2 | 4 | 4 | 4 |
| MCP gateway alongside model routing | 10 | 5 | 3 | 3 | 5 | 1 |
| Operability and performance | 10 | 4 | 3 | 5 | 5 | 2 |
| Time to day-one scope | 15 | 5 | 5 | 3 | 3 | 1 |
| **Weighted total** | 100 | **4.15** | **3.85** | **3.50** | **3.35** | **2.70** |

Notes on the scores. Portkey loses a point on vendor direction because a security vendor now owns
it and its paid features may move into that vendor's platform; the MIT licence means the bank can
keep running the open-source gateway regardless. LiteLLM loses on supply chain because of the March
2026 compromise; the mitigation is building from source at a pinned commit, which applies to any
choice. Envoy and Kong are strongest if the bank already standardises on them as API gateways
([open question 11](../overview.md#open-questions)).

## Decision

Portkey's open-source gateway, self-hosted inside the bank as the data plane, behind a thin
**key-and-budget service** we build (`03` calls it the AI gateway front). That service holds every
per-workflow and platform purpose model key; workers, agent blocks and ingestion code hold none. We do not use
Portkey's cloud control plane unless the bank approves sending configuration and metadata to it.
Configuration (aliases, keys, budgets) is generated from our registry, so the registry stays the one
home for which workflow may use which model and how much. LiteLLM is the fallback, built from source.

What we build on top, in every case: the key-and-budget service, which authenticates the caller's
workload identity and run context, attaches the key and checks the budget ledger, so workers hold no
model key; bank aliases tied to evidence (an alias change for a workflow is a re-test edit);
per-workflow keys issued at publish and held only by that service; platform purpose keys for
ingestion, playground and eval with their own budgets; budgets per workflow from the
registry, redaction rules driven by the sensitivity carried on each knowledge source and case field
(Knowledge requirement 7), failover only to aliases that have evidence for that workflow
version, and the discovery report.

### Is it needed on day one?

Yes, with a small scope. The table separates what the first email workflow needs from what can wait.

| Capability | Day one | Can wait | Why |
|---|---|---|---|
| One OpenAI-compatible endpoint; workers' egress allows only this for model traffic | Yes | | The mandate becomes a network fact from the first call, and every later control has a place to live |
| Two or three bank aliases mapped to approved model endpoints | Yes | | Workflows pin aliases, not provider model names, so a model change is visible and testable |
| Per-workflow key and hard budget, held by the key-and-budget service | Yes | | Cost per workflow is a registry field (Component 1) and a runaway loop is capped; workers holding keys would break ADR-0004's "workers hold no credentials" |
| Platform purpose keys and budgets for ingestion, playground and eval | Yes | | Embeddings for the first knowledge base and every gate eval run call models before any workflow is live |
| Metadata log to SIEM: workflow, version, alias, model, tokens, cost, latency, status | Yes | | Audit and the cost column need it; prompt bodies can stay in the run journal |
| Redaction of the email template's known sensitive fields | Yes, if the approved model endpoint is not cleared for that data | Otherwise later | Depends on [open question 13](../overview.md#open-questions) |
| Retries and timeouts | Yes | | Cheap and expected |
| Failover between providers | | Yes | Failover to an untested model is worse than a manual-handling fallback; it needs evidence per alias first |
| Guardrail library, semantic cache | | Yes | Optimisations once traffic exists |
| Discovery of unregistered model traffic elsewhere in the bank | | Yes | Needs the bank's network or proxy logs; the gateway's own traffic is already registered |
| Chargeback reports | | Yes | Built from the day-one metadata log |

**Cost of adding it later.** Every agent block written before the gateway exists would hold its own
provider keys and endpoints. Moving them later means changing each block's configuration, rotating
the keys it held, and re-running each workflow's suite because the request path changed, which is a
re-test for every published workflow. Until the last caller moves, the egress rule cannot be
switched on, so the mandate and the discovery report rest on policy rather than on the network.
The model-call history from before the switch would also be missing from the gateway log Audit
reads. The day-one scope above is a few days of configuration on an adopted gateway plus the
key-and-budget service (a small service, estimated in the [implementation plan](../../plan/implementation-plan.md)); retrofitting
grows with every workflow published without it.

## Consequences

### Strongest counter-argument and our answer

**"Portkey's best features are paid, and its new owner sells a competing security platform.
LiteLLM is more widely deployed."** The day-one scope uses only open-source features that both
products have, behind configuration we generate, so switching between them is a configuration
change and a re-test. Choosing Portkey is reversible at low cost. LiteLLM's wider use did not
prevent its March 2026 compromise, and the bank's vendor review will ask about it.

### What would change this decision

- Portkey confirms that redaction and audit logs stay paid and the bank needs them in the gateway:
  then compare the enterprise price against building redaction in our layer on either gateway.
- The bank already operates Kong or Envoy as its API gateway: then the AI gateway is a plugin set on
  that platform.
- Portkey's open-source repository stops receiving releases after the acquisition.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Self-hosted Portkey OSS gateway behind the key-and-budget service; aliases, per-workflow and platform purpose keys and budgets generated from the registry; metadata log to SIEM; egress lock; redaction if required by [open question 13](../overview.md#open-questions) | Failover with evidence per alias, guardrail library, semantic cache, discovery of unregistered traffic, chargeback |

## Sources

[envoy-aig]: https://www.truefoundry.com/blog/envoy-ai-gateway-review
[kong-ai]: https://api7.ai/kong-ai-gateway-vs-litellm
[litellm-blog]: https://docs.litellm.ai/blog/security-update-march-2026
[litellm-incident]: https://securitylabs.datadoghq.com/articles/litellm-compromised-pypi-teampcp-supply-chain-campaign/
[litellm-repo]: https://github.com/BerriAI/litellm
[panw-10q]: https://www.sec.gov/Archives/edgar/data/0001327567/000132756726000015/panw-20260430.htm
[portkey-2]: https://portkey.ai/blog/gateway-2-0/
[portkey-alt]: https://llmgateway.io/blog/portkey-alternatives
[portkey-hybrid]: https://portkey.ai/docs/self-hosting/hybrid-deployments/architecture
[portkey-repo]: https://github.com/Portkey-AI/gateway
