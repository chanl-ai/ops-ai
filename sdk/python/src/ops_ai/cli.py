"""`ops`, the one command line, sitting on this SDK: each area is a few verbs over the client's methods, never a call
of its own to the API. `ops plugin validate|test` is the operator's plugin kit (the ops-plugin-sdk package), forwarded
as it is. Exit 0 done, 1 refused or failing, 2 a usage or set-up problem."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from ._cli.agents import main as agents_main
from ._cli.workflows import main as workflows_main

# Each area's handler takes the arguments after the area's name; areas over the SDK (apps, accounts, tools, resources)
# join this table one by one.
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
    "plugin": (_plugin, "build and check a plugin: validate, test"),
    "workflows": (workflows_main, "author and run workflows: validate, apply, publish, run"),
    "agents": (agents_main, "author and chat with agents: apply, publish, chat, test"),
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
