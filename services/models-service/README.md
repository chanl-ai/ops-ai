# Models service

The console calls this the AI gateway.

Status: not started. The console screens are planned in `docs/plan/ai-gateway-console.md`.

Every model call leaves through this service: model aliases, provider keys, per-identity keys and budgets, metadata
logging, redaction and failover, in front of Portkey's open-source gateway (ADR-0008). Agent workers hold no model
keys. Production runs it as its own process.

Design: `docs/architecture/service-map.md`. Spec: `docs/specs/data-and-ai-gateways.md` 4.8, 5.8–5.10.
