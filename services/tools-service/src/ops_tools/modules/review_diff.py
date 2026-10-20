"""What a tool module review approves (c-204): the operations added, removed and changed since the published version,
the hosts its calls would reach that the published version did not, and the secrets its operations read. Sent with the
review when it opens, so the reviewer sees what was asked for even if the module is edited afterwards."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..executor import secret_names

# What a changed operation names, beside its name: the parts of a call a reviewer decides on.
COMPARED = ("method", "path", "access", "executor")


def _ever_published(m: dict[str, Any]) -> bool:
    return m["status"] == "published" or any(v["status"] in ("published", "deprecated") for v in m["versions"])


def _host(m: dict[str, Any], op: dict[str, Any]) -> str | None:
    path = str(op.get("path") or "")
    return urlsplit(path if "://" in path else str(m["endpoint"] or "")).hostname


def _summary(op: dict[str, Any]) -> dict[str, Any]:
    return {"name": op["name"], "method": op.get("method"), "path": op.get("path"), "access": op["access"]}


def _inputs(op: dict[str, Any]) -> list[str]:
    fields: list[dict[str, Any]] = list(op.get("input") or [])
    return sorted(str(f["name"]) for f in fields)


def review_diff(m: dict[str, Any]) -> dict[str, Any]:
    """The module's change since it was last published: a module never published adds every operation it has; a
    published one compares its staged operations with the published ones (its baseline)."""
    if not _ever_published(m):
        before: list[dict[str, Any]] = []
    else:
        before = list(m["baseline"] if m["baseline"] is not None else m["operations"])
    after: list[dict[str, Any]] = list(m["operations"])
    was, now = {o["id"]: o for o in before}, {o["id"]: o for o in after}
    changed: list[dict[str, Any]] = []
    for op_id in now.keys() & was.keys():
        old, new = was[op_id], now[op_id]
        fields = [k for k in COMPARED if old.get(k) != new.get(k)]
        if _inputs(old) != _inputs(new):
            fields.append("inputs")
        if fields:
            changed.append({**_summary(new), "fields": fields})
    hosts_before = {h for o in before if (h := _host(m, o))}
    hosts_after = {h for o in after if (h := _host(m, o))}
    return {
        "added": sorted((_summary(now[i]) for i in now.keys() - was.keys()), key=lambda o: o["name"]),
        "removed": sorted((_summary(was[i]) for i in was.keys() - now.keys()), key=lambda o: o["name"]),
        "changed": sorted(changed, key=lambda o: o["name"]),
        "hostsAdded": sorted(hosts_after - hosts_before),
        "secrets": sorted({s for o in after for s in secret_names(o)}),
    }
