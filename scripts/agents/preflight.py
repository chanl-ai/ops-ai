#!/usr/bin/env python3
"""Builder preflight: stop in one line when a card is not ready to build.

Usage: preflight.py <card-id>   (identity from CL_AGENT)
Exit 0 and print "ok" when ready; exit 1 and print one line saying why otherwise.

The board holds no hash field, so a changed design is detected by comparing the
design page's last commit time with the time the plan was approved.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Plans are approved by a decision event; a plan that needed no approval counts from its plan event.
APPROVAL_ACTIONS = ("approve", "decide")
DESIGN_LINK = re.compile(r"(?:docs/[\w./-]+\.html|localhost:3009/[\w./-]+\.html)")


def board_dir():
    # The board lives with the main checkout; a worktree has no board of its own.
    common = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return str(Path(common).parent) if common else str(REPO)


def read_card(card_id):
    out = subprocess.run(
        ["cl", "story", "read", card_id], capture_output=True, text=True, check=True, cwd=board_dir()
    ).stdout
    return json.loads(out)["data"]


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def approval_time(card):
    events = card.get("events", [])
    for wanted in (APPROVAL_ACTIONS, ("plan",)):
        hits = [e for e in events if any(w in e["action"] for w in wanted)]
        if hits:
            return parse_time(hits[-1]["at"])
    return None


def design_path(card):
    match = DESIGN_LINK.search((card.get("plan") or {}).get("scope", ""))
    if not match:
        return None
    link = match.group(0)
    return link[link.index("docs/") :] if "docs/" in link else link.split("3009/", 1)[1]


def last_commit_time(path):
    out = subprocess.run(
        ["git", "-C", str(REPO), "log", "-1", "--format=%cI", "--", path],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return parse_time(out) if out else None


def check(card, agent, commit_time=last_commit_time):
    """Return the refusal line, or None when the card is ready."""
    if not agent:
        return "CL_AGENT is not set: run as your own agent name"
    if card.get("holder") != agent:
        return f"{card['id']} is not claimed by {agent} (holder: {card.get('holder') or 'nobody'}): claim it first"
    plan = card.get("plan") or {}
    if not plan.get("files"):
        return f"{card['id']} has no file list in its plan: ask for the plan to name the files"
    design = design_path(card)
    if design:
        approved, changed = approval_time(card), commit_time(design)
        if approved and changed and changed > approved:
            return (
                f"design {design} changed {changed.isoformat()} after the plan was approved "
                f"{approved.isoformat()}: get the plan re-approved"
            )
    return None


def main(argv):
    if len(argv) != 2:
        print("usage: preflight.py <card-id>")
        return 1
    try:
        card = read_card(argv[1])
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, ValueError) as err:
        print(f"cannot read card {argv[1]}: {err}")
        return 1
    refusal = check(card, os.environ.get("CL_AGENT", ""))
    print(refusal or "ok")
    return 1 if refusal else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
