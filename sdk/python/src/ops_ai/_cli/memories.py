"""`opsai memories`: what the agents remember about you, as Settings > Account > Memory shows it. List it, forget one
memory or everything one agent remembers, and export it all. Each call acts on the signed-in person's own memory."""

from __future__ import annotations

import argparse

from ops_ai import OpsAI

from .chat import agent_id
from .common import client, emit, parser, refuse, table, verb_options


def main(argv: list[str]) -> int:
    ap = parser("opsai memories", "Your memories: list, forget, forget-agent, export.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("list", parents=common, help="what the agents remember about you").add_argument("--agent")
    sub.add_parser("forget", parents=common, help="forget one memory").add_argument("id")
    sub.add_parser("forget-agent", parents=common, help="forget everything one agent remembers").add_argument("agent")
    sub.add_parser("export", parents=common, help="every memory, as the export downloads it")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _agent(ops: OpsAI, name: str | None) -> str | None:
    """An agent id as given, else the one New chat names so."""
    return name if name is None or name.startswith("ag_") else agent_id(ops, name, test=False)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    agents = ops.raw.agents
    if ns.verb == "list":
        rows = agents.memory_list_memories(agent_id=_agent(ops, ns.agent))
        return table(ns, rows, "id", "agentName", "kind", "value", "createdAt")
    if ns.verb == "forget":
        agents.memory_forget_memory(ns.id)
        return emit(ns, {"forgotten": ns.id}, text=f"forgot {ns.id}")
    if ns.verb == "forget-agent":
        done = agents.memory_forget_agent_memories(agent_id=_agent(ops, ns.agent))
        return emit(ns, done)
    return emit(ns, agents.memory_export_memories())
