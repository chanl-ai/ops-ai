# ops-tool-module: add a tool module, its secret and its host

Status: current. Proven by `make skills-proof`.

skill: ops-tool-module
description: Add a tool module (OpenAPI, MCP, HTTP or a Python code tool) with its credential as a secret and its host on the egress list, then publish it through review. Use when someone wants an agent or workflow to call a new system.
targets: make usecase-test UC=uc-010, make usecase-test UC=uc-013, make usecase-test UC=uc-531

## When to use it

An agent or workflow needs to reach a system Ops AI does not call yet.

## Steps

1. A tool module belongs to one team. Create it in the console (Data Hub > Tools > New module) or through
   tools-service: `POST /v1/tool-modules` with an OpenAPI document, an MCP server or HTTP operations; for a Python
   function, `type: code` with its source, the tools it may call (`bindings`) and the secrets it may hand on by name.
2. The credential is a secret, never a literal: a Security admin adds it (`POST /v1/secrets` with the team's
   `teamId`), and the operation names it. A secret's value never comes back from any route.
3. The system's host goes on the egress list (Settings > Egress, `POST /v1/egress/hosts`); a call to any other host is
   refused.
4. A write operation gets an approval policy (approvers, step-up); reads run at once.
5. Ask for review: the workspace's Security team decides it (`POST /v1/tool-modules/{id}/reviews`), and only a published
   module can be granted to an agent or used in a workflow step.

Worked examples: `docs/usecases/tools-service/` (uc-010 a module's life, uc-013 a credential that never comes back,
uc-531 a Python function that uses a secret by name). Change no service code for one system: a tool is configuration.

## Proof

```bash proof
make usecase-test UC=uc-010 LAYER=api
make usecase-test UC=uc-013 LAYER=api
```
