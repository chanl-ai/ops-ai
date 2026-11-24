# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-772 a watched folder brings files in, api layer: docs/usecases/files-service/a-watched-folder-brings-files-in.md.
The built-in SharePoint plugin (builtin-plugins/ops_plugin_sharepoint, the copy every stack ships) runs in tools-service
against its fake from the plugins checkout (OPS_PLUGINS_REPO), served on https under graph.microsoft.com
(docs/usecases/lib/fake_sharepoint_confluence.py), with one file in the library whose size Graph reports as 30 MB. Everyone signs in through platform-service, so the seeded roles decide: Priya (admin)
connects SharePoint for team_ops, James (builder) watches a folder and presses Check now, Ravi (viewer) only reads.
files-service checks the watch through tools-service. No model is called."""

from __future__ import annotations

import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx
from fake_sharepoint_confluence import OVERSIZE_BYTES, OVERSIZE_NAME, add_oversize, connect, document_systems
from usecase_harness import PLATFORM_INTERNAL_PORT, check, files, finish, platform, tools

PASSWORD = "northfield-demo"
SHAREPOINT = "opsai.sharepoint"
NAME = f"Policies folder {int(time.time()) % 10000}"


def body(res: httpx.Response) -> Any:
    try:
        return res.json().get("data")
    except ValueError:
        return None


def signed_in(api: httpx.Client, email: str, team: str) -> dict[str, str]:
    token = body(api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}", "X-Team-Id": team}


with ExitStack() as stack:
    systems = stack.enter_context(document_systems())
    add_oversize(systems)
    g = systems.graph_ids
    api, _ = stack.enter_context(platform())
    platform_url = str(api.base_url).rstrip("/")
    gw = stack.enter_context(
        tools(
            {
                **systems.settings,
                # No working copy replaces the built-in plugins, so the run reads the copy that ships.
                "OPS_PLUGIN_PATHS": "[]",
                "OPS_CONSOLE_URL": "https://console.harborpine.test",
                "OPS_AUTH_MODE": "platform",
                "OPS_PLATFORM_URL": platform_url,
                "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
            }
        )
    )
    fs = stack.enter_context(files(Path(stack.enter_context(tempfile.TemporaryDirectory())), scanning="off"))

    priya = signed_in(api, "p.shah@harborpine.example", "team_ops")
    sam = signed_in(api, "s.adeyemi@harborpine.example", "team_security")
    james = signed_in(api, "j.richardson@harborpine.example", "team_ops")
    ravi = signed_in(api, "r.menon@harborpine.example", "team_ops")

    done = connect(gw, systems, priya, sam)
    check("1 Priya connects SharePoint for the team through Microsoft", done["sharepoint"]["done"] == 200, done)

    watch_in = {
        "name": NAME,
        "plugin": SHAREPOINT,
        "source": "files",
        "connectionId": done["sharepoint"]["account"],
        "values": {"sites": [g.SITE_HR], "libraries": [g.LIB_POLICIES]},
        "names": {"sites": {g.SITE_HR: "Human Resources"}, "libraries": {g.LIB_POLICIES: "Policies Library"}},
    }
    made = fs.post("/v1/watches", json=watch_in, headers=james)
    watch = body(made) or {}
    wid = str(watch.get("id") or "wat_missing")
    folders = [f["name"] for f in watch.get("folders") or []]
    check(
        "2 James watches the Policies Library, and the watch names its folders",
        made.status_code == 201 and folders == ["Human Resources", "Policies Library"],
        {"status": made.status_code, "said": made.text[:300]},
    )

    # S1: a Viewer reads the list and is refused every change.
    listed = fs.get("/v1/watches", headers=ravi)
    ids = [w["id"] for w in (body(listed) or {}).get("data", [])]
    refused_add = fs.post("/v1/watches", json={**watch_in, "name": "Ravi's folder"}, headers=ravi)
    refused_check = fs.post(f"/v1/watches/{wid}/check", headers=ravi)
    check(
        "3 Ravi, a viewer, lists the watch but is refused adding one and Check now",
        listed.status_code == 200
        and wid in ids
        and refused_add.status_code == 403
        and refused_check.status_code == 403,
        {"list": listed.status_code, "add": refused_add.status_code, "check": refused_check.status_code},
    )
    other = fs.get(f"/v1/watches/{wid}", headers=sam)
    check("3 another team's person does not find the watch", other.status_code == 404, other.status_code)

    # S2: Check now, a second press while it runs, then the outcome on the watch.
    asked = fs.post(f"/v1/watches/{wid}/check", headers=james)
    again = fs.post(f"/v1/watches/{wid}/check", headers=james)
    running = body(fs.get(f"/v1/watches/{wid}", headers=james)) or {}
    check(
        "4 Check now is taken, the watch shows it is checking, and a second press says a check is already running",
        asked.status_code == 202 and running.get("checking") is True and again.status_code == 409,
        {"asked": asked.status_code, "again": [again.status_code, again.text[:200]], "checking": running.get("checking")},
    )
    seen: dict[str, Any] = running
    for _ in range(120):
        seen = body(fs.get(f"/v1/watches/{wid}", headers=james)) or {}
        if not seen.get("checking"):
            break
        time.sleep(0.5)
    last = seen.get("lastCheck") or {}
    failures = last.get("failures") or []
    check(
        "5 the check brings in the library's three files and names the 30 MB file as failed, with its size",
        last.get("status") in ("success", "partial")
        and last.get("brought") == 3
        and last.get("failed") == 1
        and bool(failures)
        and OVERSIZE_NAME in str(failures[0].get("path"))
        and failures[0].get("size") == OVERSIZE_BYTES
        and seen.get("filesInFiles") == 3
        and bool(seen.get("lastCheckAt")),
        {"lastCheck": last, "filesInFiles": seen.get("filesInFiles")},
    )

    events = (body(fs.get(f"/v1/watches/{wid}/events", headers=ravi)) or {}).get("data", [])
    kinds = sorted(e["kind"] for e in events)
    failed = [e for e in events if e["kind"] == "failed"]
    check(
        "6 the watch's events list three new files and one failed file with its size, readable by a viewer",
        kinds == ["failed", "new", "new", "new"] and failed[0].get("size") == OVERSIZE_BYTES,
        events,
    )

    leave = next((e for e in events if e["kind"] == "new" and str(e.get("path", "")).endswith("leave.md")), {})
    detail = body(fs.get(f"/v1/files/{leave.get('fileId')}", headers=ravi)) or {}
    source = detail.get("source") or {}
    check(
        "7 a brought-in file says which watched folder and path it came from",
        source.get("watchId") == wid and source.get("watchName") == NAME and "leave.md" in str(source.get("path")),
        {"name": detail.get("name"), "source": source},
    )

finish()
