"""Shared argument parsing, client construction and printing for `ops` areas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._io import load_data
from ops_ai.errors import OpsError


def parser(prog: str, description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description=description)
    ap.add_argument("--profile")
    ap.add_argument("--team")
    ap.add_argument("--base-url")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--quiet", action="store_true")
    return ap


def client(ns: argparse.Namespace) -> OpsAI:
    return OpsAI(profile=ns.profile, team=ns.team, base_url=ns.base_url)


def payload(value: str | None) -> Any:
    if value is None or value == "":
        return {}
    if value == "-":
        return load_data(sys.stdin.read())
    if "=" in value and not Path(value).exists() and not value.startswith("{"):
        out: dict[str, Any] = {}
        for part in value.split(","):
            key, _, item = part.partition("=")
            out[key] = item
        return out
    return load_data(value)


def emit(ns: argparse.Namespace, data: Any, *, text: str | None = None) -> int:
    if ns.as_json:
        sys.stdout.write(json.dumps(data, default=str) + "\n")
        return 0
    if ns.quiet:
        return 0
    sys.stdout.write((text if text is not None else _plain(data)) + "\n")
    return 0


def refuse(exc: BaseException) -> int:
    if isinstance(exc, OpsError):
        path = exc.details.get("path") if isinstance(exc.details, dict) else None
        where = path[0] if isinstance(path, list) and path else path
        sys.stderr.write(f"{exc.code}: {where}: {exc.message}\n" if where else f"{exc.code}: {exc.message}\n")
        return 1
    if isinstance(exc, NotImplementedError):
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stderr.write(f"{exc}\n")
    return 1 if isinstance(exc, ValueError) else 2


def _plain(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str)
