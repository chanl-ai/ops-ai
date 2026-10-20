# ops_engine

The workflow runner's library: the node type registry, v2 workflow definitions and their validation, the compiler to
LangGraph, the node wrapper with its step journal, the work queue and the worker loop. It imports nothing from
`ops_agents`; it reaches tools, reviews, leases and events through the ports in `ports.py`, which agents-service
implements.

Design: [docs/architecture/workflow-runner.md](../../docs/architecture/workflow-runner.md). Node types:
[workflow-nodes.md](../../.codeloop/wiki/concepts/workflow-nodes.md).

Tests: `uv run pytest packages/ops_engine/tests`.
