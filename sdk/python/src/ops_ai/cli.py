"""`ops`, the one command line, sitting on this SDK: each area is a few verbs over the client's methods, never a call
of its own to the API. `ops plugin validate|test` is the operator's plugin kit (the ops-plugin-sdk package), forwarded
as it is. Exit 0 done, 1 refused or failing, 2 a usage or set-up problem."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from ._cli.agents import main as agents_main
from ._cli.apps import main as apps_main
from ._cli.chat import main as chat_main
from ._cli.connectors import main as connectors_main
from ._cli.kb import main as kb_main
from ._cli.login import main as login_main
from ._cli.memories import main as memories_main
from ._cli.people import models_main, people_main
from ._cli.records import cases_main, documents_main, files_main
from ._cli.resources import main as resources_main
from ._cli.runs import runs_main, tasks_main
from ._cli.testdata import main as testdata_main
from ._cli.tools import main as tools_main
from ._cli.workflows import main as workflows_main

# Each area's handler takes the arguments after the area's name.
Area = Callable[[list[str]], int]


def _plugin(argv: list[str]) -> int:
    # The plugin kit is a separate package an operator installs beside the SDK: a developer who only calls the API
    # needs neither its manifest checker nor its test runner, so the SDK depends on nothing for it.
    try:
        from ops_plugin_sdk.cli import main as plugin_main  # noqa: PLC0415
    except ImportError:
        sys.stderr.write("ops plugin: the plugin kit is not installed; install ops-ai[plugin]\n")
        return 2
    return plugin_main(["plugin", *argv])


AREAS: dict[str, tuple[Area, str]] = {
    "login": (login_main, "sign in and keep the session in a profile"),
    "plugin": (_plugin, "build and check a plugin: validate, test"),
    "workflows": (workflows_main, "author and run workflows: validate, apply, publish, run"),
    "agents": (agents_main, "author and chat with agents: apply, publish, chat, test"),
    "chat": (chat_main, "chat as the chat screen does: say, show, calls, connected, approve, reject, submit"),
    "resources": (
        resources_main,
        "an app's agents, skills, workflows and document types: list, plan, add, update, remove",
    ),
    "kb": (kb_main, "knowledge: bases, sources, items, add-file, add-text, sync, search, changes"),
    "apps": (apps_main, "apps: list, show, add-tool, accounts, mine, connect, test, auth-configs"),
    "connectors": (connectors_main, "your connectors, one row per app that acts as you: list, disconnect"),
    "tools": (tools_main, "tools: list, show, run (mock or real), calls"),
    "runs": (runs_main, "workflow runs: list, start, show, events, cancel, retry"),
    "tasks": (tasks_main, "Human Tasks: list, show, decide"),
    "cases": (cases_main, "cases: list, show, note"),
    "files": (files_main, "files: list, show, upload, limits"),
    "documents": (documents_main, "document types and extractions"),
    "people": (people_main, "members, invites (printed unless --send), roles, me"),
    "models": (models_main, "model aliases, providers, keys, and a test turn (--confirm)"),
    "memories": (memories_main, "your memories: list, forget, forget-agent, export"),
    "test-data": (testdata_main, "list what test runs made ([test] prefix); clean --confirm removes it"),
}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="ops", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="area", required=True, metavar="area")
    for name, (_, text) in AREAS.items():
        sub.add_parser(name, help=text, add_help=False)
    # Only the area is parsed here: everything after it belongs to the area's own parser.
    if not args or args[0] not in AREAS:
        ap.parse_args(args)  # prints usage and exits 2 for an unknown or missing area, or prints help and exits 0
        return 2
    handler, _ = AREAS[args[0]]
    return handler(args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
