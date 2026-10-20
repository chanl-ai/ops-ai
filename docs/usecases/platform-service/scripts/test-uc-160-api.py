"""uc-160 password sign-in and reset, api layer: docs/usecases/platform-service/password-sign-in-and-reset.md."""

from __future__ import annotations

import json
import re

from usecase_harness import bearer, check, finish, signed_in, signin_stack

RAVI = "r.menon@northfieldbank.com"
NEW = "teller password 2026"

with signin_stack() as (api, _, mail):
    before = signed_in(api, RAVI)
    r = api.post("/v1/auth/password/forgot", json={"email": RAVI})
    check("a reset request is answered 204", r.status_code == 204, r.status_code)
    sent = [json.loads(f.read_text()) for f in mail.glob("*.json")]
    link = re.search(r"/reset-password/(prt_[A-Za-z0-9_-]+)", sent[0]["body"]) if len(sent) == 1 else None
    check("one reset mail goes to Ravi with a console link", bool(link) and sent[0]["to"] == [RAVI], sent)
    token = link.group(1) if link else "prt_missing000"
    r = api.post("/v1/auth/password/forgot", json={"email": "nobody@northfieldbank.com"})
    check(
        "a request for an unknown email is answered the same and sends nothing",
        r.status_code == 204 and len(list(mail.glob("*.json"))) == 1,
    )

    r = api.post("/v1/auth/password/reset", json={"token": token, "password": NEW})
    check("the link sets the new password (204)", r.status_code == 204, r.text[:200])
    r = api.post("/v1/auth/password/reset", json={"token": token, "password": "another password 99"})
    check(
        "the link works once (400 reset_invalid)",
        r.status_code == 400 and r.json()["error"]["code"] == "reset_invalid",
        r.text[:200],
    )
    r = api.get("/v1/auth/session", headers=bearer(before))
    check("the reset ended Ravi's earlier session (401)", r.status_code == 401, r.status_code)

    r = api.post("/v1/auth/sign-in", json={"email": RAVI, "password": NEW})
    principal = r.json()["data"]["principal"] if r.status_code == 200 else {}
    check(
        "the new password signs Ravi in as a password session", principal.get("authMethod") == "password", r.text[:200]
    )
    r = api.post("/v1/auth/sign-in", json={"email": RAVI, "password": "northfield-demo"})
    check("the demo password no longer opens his account (401)", r.status_code == 401, r.status_code)
    fresh = signed_in(api, RAVI, NEW)
    r = api.post("/v1/auth/step-up", json={"password": NEW}, headers=bearer(fresh))
    check("step-up takes the stored password", r.status_code == 200, r.text[:200])

finish()
