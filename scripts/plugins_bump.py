"""Moves every pin in deploy/plugins.json to the plugins repository's current main, or to REF, and prints each
plugin's old and new commit.

    python scripts/plugins_bump.py [--ref main]

REF is a branch, tag or commit of the pinned repository; the file always records the full commit it resolves to, since
bake_plugins.py refuses anything that can move."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PINS = Path(__file__).resolve().parents[1] / "deploy" / "plugins.json"
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def resolve(source: str, ref: str) -> str:
    """The full commit `ref` names in `source`."""
    if COMMIT.match(ref):
        return ref
    out = subprocess.run(["git", "ls-remote", source, ref, f"{ref}^{{}}"], capture_output=True, text=True, check=False)
    lines = [ln.split() for ln in out.stdout.splitlines() if ln.strip()]
    # An annotated tag lists its own object first and the commit it points at on the ^{} line.
    peeled = [sha for sha, name in lines if name.endswith("^{}")]
    plain = [sha for sha, _ in lines]
    sha = (peeled or plain or [""])[0]
    if out.returncode != 0 or not COMMIT.match(sha):
        raise SystemExit(f"plugins_bump: {source} has no {ref!r} ({out.stderr.strip() or 'not found'})")
    return sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move the plugin pins to a newer commit.")
    parser.add_argument("--ref", default="main")
    args = parser.parse_args(argv)
    data = json.loads(PINS.read_text())
    resolved: dict[str, str] = {}
    for pin in data["plugins"]:
        source = pin["source"]
        new = resolved.setdefault(source, resolve(source, args.ref))
        sys.stdout.write(
            f"{pin['path']}: {pin['ref'][:12]} -> {new[:12]}{'' if new != pin['ref'] else ' (unchanged)'}\n"
        )
        pin["ref"] = new
    PINS.write_text(json.dumps(data, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
