"""uc-213 a workspace proves its email domain by DNS before it routes sign-in, api layer:
docs/usecases/platform-service/sign-in-providers-and-domain-proof.md."""

from __future__ import annotations

import secrets

from usecase_harness import SIGNIN_SECRET, bearer, check, data, finish, signed_in, signin_stack

WANJIRU, JAMES = "w.kamau@harborpine.example", "j.richardson@harborpine.example"

with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.harborpine.test"
    james = bearer(signed_in(api, JAMES), "team_ops")
    admin = bearer(signed_in(api, WANJIRU), "team_security")
    r = api.get("/v1/settings/sign-in/secret-names", headers=james)
    check("James, a builder, cannot read the secret names (403)", r.status_code == 403, r.status_code)
    r = api.get("/v1/settings/sign-in/secret-names", headers=admin)
    check(
        "Wanjiru reads the secret names, never values",
        r.status_code == 200 and data(r) == [SIGNIN_SECRET],
        r.text[:200],
    )
    api.put("/v1/settings/sign-in/providers/password", json={"kind": "password", "label": "Password"}, headers=admin)
    provider = {
        "kind": "oidc",
        "label": "Harbor & Pine SSO",
        "domains": [zone],
        "oidc": {
            "issuer": f"{str(idp.base_url).rstrip('/')}/oidc/northfield",
            "clientId": "ops-console",
            "clientSecretRef": SIGNIN_SECRET,
        },
        "jit": {"team": "team_ops", "role": "chat_user"},
    }
    r = api.put("/v1/settings/sign-in/providers/oidc-northfield", json=provider, headers=admin)
    saved = data(r) if r.status_code == 200 else {}
    claim = next((c for c in saved.get("verification", []) if c["domain"] == zone), {})
    value = claim.get("record", {}).get("value", "")
    check(
        "the saved provider lists the domain as pending with its TXT record",
        claim.get("verifiedAt") is None and value.startswith("ops-ai-verify="),
        r.text[:300],
    )
    teller = f"new.teller@{zone}"
    r = api.post("/v1/auth/options", json={"email": teller})
    check(
        "the pending domain sends nobody to the provider", r.status_code == 200 and data(r)["sso"] is None, r.text[:200]
    )
    r = api.post("/v1/auth/sso/start", json={"email": teller})
    check("an SSO start for the pending domain is refused (400)", r.status_code == 400, r.status_code)

    verify = f"/v1/settings/sign-in/domains/{zone}/verify"
    r = api.post(verify, headers=james)
    check("James cannot verify a domain (403)", r.status_code == 403, r.status_code)
    r = api.post(verify, headers=admin)
    check(
        "verify with no TXT record is refused with what DNS held (422)",
        r.status_code == 422 and r.json()["error"]["code"] == "domain_unverified",
        r.text[:200],
    )
    idp.put(f"/dns/txt/{zone}", json={"values": ["ops-ai-verify=wrong", "v=spf1 -all"]}).raise_for_status()
    r = api.post(verify, headers=admin)
    check(
        "verify with a wrong TXT record names what it found (422)",
        r.status_code == 422 and "ops-ai-verify=wrong" in r.json()["error"]["message"],
        r.text[:200],
    )
    idp.put(f"/dns/txt/{zone}", json={"values": [value, "v=spf1 -all"]}).raise_for_status()
    r = api.post(verify, headers=admin)
    proven = (
        next((c for c in data(r).get("verification", []) if c["domain"] == zone), {}) if r.status_code == 200 else {}
    )
    check("verify with the published record passes (200)", bool(proven.get("verifiedAt")), r.text[:200])
    r = api.post("/v1/auth/options", json={"email": teller})
    check(
        "the verified domain now signs in through Harbor & Pine SSO",
        r.status_code == 200 and (data(r)["sso"] or {}).get("label") == "Harbor & Pine SSO",
        r.text[:200],
    )

    r = api.put(
        "/v1/settings/sign-in/providers/oidc-northfield", json={**provider, "label": "Harbor & Pine"}, headers=admin
    )
    kept = next((c for c in data(r).get("verification", []) if c["domain"] == zone), {}) if r.status_code == 200 else {}
    check("saving the provider again keeps the domain verified", bool(kept.get("verifiedAt")), r.text[:300])
    r = api.put("/v1/settings/sign-in/providers/oidc-second", json={**provider, "label": "Second"}, headers=admin)
    check(
        "a second provider listing the same domain is refused (409)",
        r.status_code == 409 and r.json()["error"]["code"] == "domain_taken",
        r.text[:200],
    )

finish()
