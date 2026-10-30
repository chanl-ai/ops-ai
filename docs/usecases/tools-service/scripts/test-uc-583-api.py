"""uc-583, api layer: docs/usecases/tools-service/plugin-sign-in-with-a-certificate.md, stories S1 to S4.

platform-service signs the seeded people in and holds the install switch; tools-service runs with plugins on and loads
the three test plugins in services/tools-service/tests/plugin_signed (OPS_PLUGIN_PATHS); the fake sign-in
(docs/usecases/lib/fake_token_endpoint.py) checks each assertion as Microsoft Entra does and answers Google and
DocuSign style JWT grants. No model call."""

from __future__ import annotations

import base64
import json
import time
import uuid
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

import httpx
import jwt
from fake_token_endpoint import LOGIN_HOST, make_pair, token_endpoint
from usecase_harness import (
    LOG_DIR,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    bearer,
    check,
    data,
    finish,
    platform,
    service_headers,
    signed_in,
    tools,
    until,
)
from usecase_harness import ROOT as REPO

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
SIGNED = REPO / "services/tools-service/tests/plugin_signed"
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps(sorted(str(p) for p in SIGNED.glob("signed_*")))}
TENANT: dict[str, str] = {}
SEEN: list[str] = []


def kept(r: httpx.Response) -> httpx.Response:
    SEEN.append(r.text)
    return r


def call(gw: httpx.Client, tool: str, team: str = "team_ops") -> httpx.Response:
    """A gateway call as agents-service makes it for a run in `team` with nobody behind it: a read, runs at once."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team=team)
    body = {"tool": tool, "input": {"id": "agr-2207"}, "key": uuid4().hex, "runContext": {"environment": "production"}}
    return kept(gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": team}))


def output(r: httpx.Response) -> dict[str, Any]:
    return dict((data(r) or {}).get("output") or {}) if r.status_code == 200 else {}


def error(r: httpx.Response) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        return {}
    found = (body.get("data") or {}).get("output", {}).get("error") if body.get("data") else body.get("error")
    return dict(found or {})


def turn_on(gw: httpx.Client, who: dict[str, str], plugin: str, **body: Any) -> httpx.Response:
    return kept(gw.put(f"/v1/plugins/{plugin}/team", json={"enabled": True, **body}, headers=who))


def health(gw: httpx.Client, who: dict[str, str], connection_id: str) -> dict[str, Any]:
    r = kept(gw.post(f"/v1/connections/{connection_id}/test", json={"environment": "production"}, headers=who))
    return dict((data(r) or {}).get("health") or {"status": f"http {r.status_code}", "text": r.text[:200]})


def connection(gw: httpx.Client, who: dict[str, str], connection_id: str) -> dict[str, Any]:
    return dict(data(kept(gw.get(f"/v1/connections/{connection_id}", headers=who))) or {})


def requests_to(fake: Any, system: str) -> list[dict[str, Any]]:
    return [r for r in fake.state()["token_requests"] if r["system"] == system]


def b64(part: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()


def forged(m: dict[str, Any], *, lifetime: int = 300, jti: str | None = None, alg: str | None = None) -> str:
    """An assertion for the Entra app as a client other than tools-service might send it."""
    s = m["systems"]["entra"]
    now = int(time.time())
    claims = {"iss": s["client_id"], "sub": s["client_id"], "aud": s["token_url"], "iat": now, "nbf": now,
              "exp": now + lifetime, "jti": jti or uuid.uuid4().hex}  # fmt: skip
    if alg == "none":
        return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."
    pair = s["pair"]
    return jwt.encode(claims, pair.key, algorithm="RS256", headers={"x5t#S256": pair.thumbprint})


def entra_form(assertion: str, client_id: str) -> dict[str, str]:
    return {"grant_type": "client_credentials", "client_id": client_id,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion}  # fmt: skip


with ExitStack() as stack:
    m = stack.enter_context(token_endpoint())
    fake = m["fake"]
    entra, google, docusign = (m["systems"][s] for s in ("entra", "google", "docusign"))
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools({**m["settings"], **AUTH, **PLUGINS, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    wanjiru = bearer(signed_in(api, "w.kamau@harborpine.example"), "team_platform")

    loaded = data(gw.get("/v1/plugins", headers=priya)) or {}
    ids = sorted(p["id"] for p in loaded.get("plugins", []))
    policy = api.put("/v1/policies/plugins", json={"value": {i: {"enabled": True} for i in ids}}, headers=sam)
    until(
        lambda: all(p["installOn"] for p in (data(gw.get("/v1/plugins", headers=priya)) or {}).get("plugins", [])),
        timeout=30,
    )
    allowed = [gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-583"}, headers=sam) for h in m["hosts"]]
    allowed.append(gw.post("/v1/egress/ranges", json={"value": m["range"], "note": "uc-583"}, headers=sam))
    check(
        "1 the three certificate plugins load and turn on for the install, and Security lists the sign-in's hosts",
        ids == ["test.docusign", "test.entra", "test.google"] and policy.status_code == 200
        and all(r.status_code in (200, 201, 409) for r in allowed),
        {"ids": ids, "failed": loaded.get("failed"), "policy": policy.text[:200]},
    )  # fmt: skip

    # S1. An Entra app proves itself with its certificate: no client secret is sent, and the call runs.
    pair = entra["pair"]
    signed = {"clientAuth": "private_key_jwt", "signingCertificate": pair.cert, "signingKey": pair.key}
    on = turn_on(gw, priya, "test.entra", clientId=entra["client_id"], credentials=signed)
    entra_id = str((data(on) or {}).get("connectionId") or "con_missing")
    tested = health(gw, priya, entra_id)
    called = call(gw, "entra_get_record")
    asked = requests_to(fake, "entra")
    check(
        "2 an Entra app turned on with its certificate passes Test connection and a run's call reads the agreement; "
        "every token request carried a signed assertion and no client secret",
        on.status_code == 200 and tested.get("status") == "ok"
        and output(called).get("record", {}).get("id") == "agr-2207"
        and asked and all(r.get("accepted") and "client_assertion" in r["fields"] for r in asked)
        and not any("client_secret" in r["fields"] for r in asked),
        {"on": on.text[:300], "health": tested, "call": called.text[:300], "token requests": asked},
    )  # fmt: skip

    # S2. Service accounts whose grant is the signed JWT: Google (scopes as a claim) and DocuSign (acting as a user).
    g_pair = google["pair"]
    g_on = turn_on(gw, priya, "test.google", clientId=google["client_id"],
                   credentials={"scopeIn": "claim", "signingKey": g_pair.key})  # fmt: skip
    d_pair = docusign["pair"]
    d_on = turn_on(gw, priya, "test.docusign", clientId=docusign["client_id"],
                   credentials={"subject": "user-5c0e2a", "audience": "account-d.docusign.com",
                                "signingCertificate": d_pair.cert, "signingKey": d_pair.key})  # fmt: skip
    g_call, d_call = call(gw, "google_get_record"), call(gw, "docusign_get_record")
    g_asked, d_asked = requests_to(fake, "google"), requests_to(fake, "docusign")
    check(
        "3 a Google service account and a DocuSign integration each get a token with the signed JWT as the grant, no "
        "client sent, and their calls read the agreement as the account and as the DocuSign user",
        g_on.status_code == 200 and d_on.status_code == 200
        and output(g_call).get("as") == google["client_id"] and output(d_call).get("as") == "user-5c0e2a"
        and [r["fields"] for r in g_asked[:1]] == [["assertion", "grant_type"]]
        and [r["fields"] for r in d_asked[:1]] == [["assertion", "grant_type", "scope"]]
        and all(r.get("accepted") for r in [*g_asked, *d_asked]),
        {"google": (g_on.text[:200], g_call.text[:200], g_asked), "docusign": (d_on.text[:200], d_call.text[:200],
         d_asked)},
    )  # fmt: skip

    # S3. Assertions the sign-in refuses. First straight to the fake, so the refusals below are its own checks.
    cid = entra["client_id"]
    replayed = forged(m, jti="jti-used-once")
    tries = {
        "none": fake.token("entra", entra_form(forged(m, alg="none"), cid)),
        "too long": fake.token("entra", entra_form(forged(m, lifetime=3600), cid)),
        "first": fake.token("entra", entra_form(replayed, cid)),
        "replay": fake.token("entra", entra_form(replayed, cid)),
    }
    said = {k: (status, body.get("error_description", "")) for k, (status, body) in tries.items()}
    check(
        "4 the fake sign-in refuses an unsigned assertion, one that lives an hour, and a replay of one it accepted",
        said["first"][0] == 200 and all(said[k][0] == 401 for k in ("none", "too long", "replay"))
        and "algorithm" in said["none"][1] and "ten minutes" in said["too long"][1] and "replay" in said["replay"][1],
        said,
    )  # fmt: skip

    # Then through the platform: a team uploads a pair the app was never registered with.
    other = m["unregistered"]
    before = len(requests_to(fake, "entra"))
    wrong_on = turn_on(gw, wanjiru, "test.entra", clientId=entra["client_id"],
                       credentials={"clientAuth": "private_key_jwt", "signingCertificate": other.cert,
                                    "signingKey": other.key})  # fmt: skip
    wrong_id = str((data(wrong_on) or {}).get("connectionId") or "con_missing")
    wrong_call = call(gw, "entra_get_record", team="team_platform")
    wrong_asked = requests_to(fake, "entra")[before:]
    wrong_status = connection(gw, wanjiru, wrong_id).get("status")
    check(
        "5 a certificate the app was not registered with fails the call AUTH_FAILED naming the sign-in host and its "
        "reason, nothing is retried with a secret, and the connection needs reconnecting",
        wrong_on.status_code == 200 and error(wrong_call).get("code") == "AUTH_FAILED"
        and LOGIN_HOST in str(error(wrong_call).get("message")) and "invalid_client" in str(error(wrong_call))
        and len(wrong_asked) == 1 and "client_secret" not in wrong_asked[0]["fields"]
        and "thumbprint" in str(wrong_asked[0].get("refused")) and wrong_status == "needs_reconnect",
        {"call": wrong_call.text[:300], "asked": wrong_asked, "status": wrong_status},
    )  # fmt: skip

    # S4. The pair at save, the certificate on every read, and an expired one.
    mixed = turn_on(gw, wanjiru, "test.google", clientId=google["client_id"],
                    credentials={"signingCertificate": entra["pair"].cert, "signingKey": g_pair.key})  # fmt: skip
    read = connection(gw, priya, entra_id)
    shown = ((read.get("environments") or {}).get("production") or {}).get("certificate") or {}
    expiring = make_pair("ops-ai-acme-app", days=-1)
    old_before = len(fake.state()["token_requests"])
    old_on = turn_on(gw, wanjiru, "test.docusign", clientId=docusign["client_id"],
                     credentials={"subject": "user-5c0e2a", "audience": "account-d.docusign.com",
                                  "signingCertificate": expiring.cert, "signingKey": expiring.key})  # fmt: skip
    old_id = str((data(old_on) or {}).get("connectionId") or "con_missing")
    old_call = call(gw, "docusign_get_record", team="team_platform")
    old_read = connection(gw, wanjiru, old_id)
    thumb_hex = base64.urlsafe_b64decode(pair.thumbprint + "=").hex()
    check(
        "6 a key saved with another certificate is refused naming both; a read shows the certificate's thumbprint "
        "and expiry and never its key; an expired certificate fails the call before any request, and the connection "
        "says it needs a new certificate",
        mixed.status_code == 400 and "Signing key" in mixed.text and "Signing certificate" in mixed.text
        and shown.get("thumbprint") == thumb_hex and shown.get("notAfter") and shown.get("expiresSoon") is False
        and pair.key.split("\n")[1] not in json.dumps(read)
        and error(old_call).get("code") == "AUTH_FAILED" and "expired on" in str(error(old_call).get("message"))
        and len(fake.state()["token_requests"]) == old_before
        and old_read.get("status") == "needs_reconnect" and "expired" in str(old_read.get("statusDetail")),
        {"mixed": mixed.text[:300], "shown": shown, "expired call": old_call.text[:300],
         "status": (old_read.get("status"), old_read.get("statusDetail"))},
    )  # fmt: skip

    # No answer read above, and no tools-service log line, carries a private key or an assertion.
    logs = "".join(p.read_text(errors="replace") for p in LOG_DIR.glob(f"tools-{TOOLS_PORT}.log"))
    keys = [p.key.split("\n")[1] for p in (pair, g_pair, d_pair, other, expiring)]
    leaked = [i for i, k in enumerate(keys) if any(k in t for t in [*SEEN, logs])]
    leaked += ["assertion" for t in [*SEEN, logs] if "client_assertion=" in t or '"assertion"' in t]
    check(
        "7 no API answer or tools-service log line shows a signing key or an assertion",
        not leaked and len(SEEN) > 10 and bool(logs),
        {"leaked": leaked, "answers read": len(SEEN)},
    )

finish()
