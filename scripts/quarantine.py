#!/usr/bin/env python3
"""The flaky-test quarantine: a checked-in list (config/quarantine.json) CI reads.

    python3 scripts/quarantine.py list
    python3 scripts/quarantine.py add <id> --owner NAME --until YYYY-MM-DD --why TEXT
    python3 scripts/quarantine.py remove <id>
    python3 scripts/quarantine.py check          # exit 1 on an entry without owner or date, or past its date
    python3 scripts/quarantine.py --self-test

An id is a use case (`uc-123`), or one of its layers (`uc-123:ui`). A quarantined use case still runs, but its
failure does not fail the run (scripts/ci_usecases.py). The expiry date is the limit on how long a flaky test may sit
here: after it, `check` fails until the owner fixes the test and removes the entry, or extends the date on purpose.
Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "config/quarantine.json"
ID = re.compile(r"^uc-\d+(:[a-z]+)?$")
MAX_DAYS = 30


def load(path: Path = FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(data: dict[str, Any], path: Path = FILE) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def problems(data: dict[str, Any], today: dt.date) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for e in data.get("entries", []):
        uid = str(e.get("id", ""))
        if not ID.match(uid):
            out.append(f"{uid or '(no id)'}: not a use case id (uc-123 or uc-123:layer)")
        if uid in seen:
            out.append(f"{uid}: listed twice")
        seen.add(uid)
        if not str(e.get("owner", "")).strip():
            out.append(f"{uid}: no owner")
        try:
            until = dt.date.fromisoformat(str(e.get("expires", "")))
        except ValueError:
            out.append(f"{uid}: expires is not a YYYY-MM-DD date")
            continue
        if until < today:
            out.append(f"{uid}: expired {until} (owner {e.get('owner')}); fix the test and remove the entry")
    return out


def active(data: dict[str, Any], today: dt.date) -> set[str]:
    """Ids that do not gate today: an expired entry stops protecting its test, so the test gates again."""
    return {e["id"] for e in data.get("entries", []) if dt.date.fromisoformat(e["expires"]) >= today}


def covers(ids: set[str], item: str) -> bool:
    """`uc-1` quarantines every layer of uc-1; `uc-1:ui` only that layer."""
    return item in ids or item.partition(":")[0] in ids


def add(data: dict[str, Any], uid: str, who: tuple[str, str, str], today: dt.date) -> None:
    """`who` is (owner, until, why)."""
    owner, until, why = who
    if not ID.match(uid):
        raise SystemExit(f"quarantine: '{uid}' is not a use case id (uc-123 or uc-123:layer)")
    when = dt.date.fromisoformat(until)
    if when < today or (when - today).days > MAX_DAYS:
        raise SystemExit(
            f"quarantine: UNTIL must be within the next {MAX_DAYS} days ({today} to {today + dt.timedelta(MAX_DAYS)})"
        )
    if not owner.strip() or not why.strip():
        raise SystemExit("quarantine: OWNER and WHY are required")
    data["entries"] = [e for e in data.get("entries", []) if e["id"] != uid]
    data["entries"].append({"id": uid, "owner": owner, "expires": until, "reason": why, "added": str(today)})


def remove(data: dict[str, Any], uid: str) -> bool:
    before = len(data.get("entries", []))
    data["entries"] = [e for e in data.get("entries", []) if e["id"] != uid]
    return len(data["entries"]) < before


def self_test() -> int:
    today = dt.date(2026, 11, 26)
    data: dict[str, Any] = {"entries": []}
    add(data, "uc-12", ("maya", "2026-12-10", "times out on a cold runner"), today)
    add(data, "uc-30:ui", ("lee", "2026-12-01", "screenshot race"), today)
    ok = [
        problems(data, today) == [],
        active(data, today) == {"uc-12", "uc-30:ui"},
        covers({"uc-12"}, "uc-12:api") and covers({"uc-30:ui"}, "uc-30:ui") and not covers({"uc-30:ui"}, "uc-30:api"),
        # An entry past its date stops protecting its test and is reported.
        active(data, dt.date(2026, 12, 2)) == {"uc-12"},
        any("expired" in p for p in problems(data, dt.date(2026, 12, 2))),
        problems({"entries": [{"id": "uc-1", "owner": "", "expires": "2026-12-01"}]}, today) == ["uc-1: no owner"],
        any("not a YYYY" in p for p in problems({"entries": [{"id": "uc-1", "owner": "a"}]}, today)),
        remove(data, "uc-12") and not remove(data, "uc-12"),
    ]
    for bad in (("uc-9", "a", "2027-06-01", "w"), ("uc-9", "", "2026-12-01", "w"), ("x", "a", "2026-12-01", "w")):
        try:
            add(data, bad[0], bad[1:], today)
            ok.append(False)
        except SystemExit:
            ok.append(True)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "q.json"
        save(data, p)
        ok.append(load(p) == data)
    print("quarantine self-test: " + ("ok" if all(ok) else f"FAILED {ok}"))
    return 0 if all(ok) else 1


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    a = sub.add_parser("add")
    a.add_argument("id")
    a.add_argument("--owner", required=True)
    a.add_argument("--until", required=True)
    a.add_argument("--why", required=True)
    r = sub.add_parser("remove")
    r.add_argument("id")
    args = ap.parse_args(argv)
    today = dt.date.today()
    data = load()
    if args.cmd == "list":
        for e in data["entries"]:
            print(f"{e['id']:12} {e['expires']}  {e['owner']}  {e.get('reason', '')}")
        print(f"{len(data['entries'])} quarantined")
        return 0
    if args.cmd == "check":
        found = problems(data, today)
        for p in found:
            print(f"quarantine: {p}")
        print(f"quarantine: {len(data['entries'])} entries, {len(found)} problems")
        return 1 if found else 0
    if args.cmd == "add":
        add(data, args.id, (args.owner, args.until, args.why), today)
        save(data)
        print(f"quarantine: {args.id} until {args.until}, owner {args.owner}")
        return 0
    if not remove(data, args.id):
        print(f"quarantine: {args.id} is not listed", file=sys.stderr)
        return 1
    save(data)
    print(f"quarantine: {args.id} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
