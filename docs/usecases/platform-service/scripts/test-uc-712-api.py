"""uc-712 company sign-in required, with a break-glass Security admin, api layer:
docs/usecases/platform-service/company-sign-in-required-and-break-glass.md."""

from __future__ import annotations

from usecase_harness import bearer, check, finish, set_provider, signed_in, signin_stack

WANJIRU, SAM = "w.kamau@harborpine.example", "s.adeyemi@harborpine.example"
DOMAIN = "harborpine.example"


def password(api: object, email: str) -> int:
    return api.post("/v1/auth/sign-in", json={"email": email, "password": "northfield-demo"}).status_code  # type: ignore[attr-defined]


with signin_stack() as (api, idp, _):
    admin = bearer(signed_in(api, WANJIRU), "team_security")
    sam_id = str(signed_in(api, SAM).get("principal", {}).get("sub", ""))
    base = str(idp.base_url).rstrip("/")
    r = set_provider(api, idp, "password", {"kind": "password", "label": "Password"}, admin)
    check("Wanjiru keeps passwords on beside the company provider (200)", r.status_code == 200, r.text[:200])
    saml = {
        "kind": "saml",
        "label": "Harbor & Pine SAML",
        "domains": [DOMAIN],
        "saml": {
            "idpEntityId": f"{base}/saml/northfield",
            "ssoUrl": f"{base}/saml/northfield/sso",
            "certificate": idp.get("/saml/northfield/certificate").text,
        },
    }
    r = set_provider(api, idp, "saml-harborpine", saml, admin)
    check("Wanjiru sets the SAML provider for harborpine.example (200)", r.status_code == 200, r.text[:200])

    r = api.put("/v1/policies/companySignInRequired", json={"value": True}, headers=admin)
    check(
        "company sign-in cannot be required with nobody on the break-glass list (409 break_glass_none)",
        r.status_code == 409 and r.json()["error"]["code"] == "break_glass_none",
        r.text[:200],
    )
    r = api.put(f"/v1/settings/sign-in/break-glass/{sam_id}", headers=admin)
    check("Wanjiru names Sam, a Security admin, as break-glass (200)", r.status_code == 200, r.text[:200])
    r = api.put("/v1/policies/companySignInRequired", json={"value": True}, headers=admin)
    check("Wanjiru requires company sign-in (200)", r.status_code == 200, r.text[:200])

    check("Wanjiru's password is now refused like a wrong one (401)", password(api, WANJIRU) == 401)
    check("Sam, break-glass, still signs in with his password (200)", password(api, SAM) == 200)
    r = api.delete(f"/v1/settings/sign-in/break-glass/{sam_id}", headers=admin)
    check(
        "the last break-glass account cannot be removed while required (409 break_glass_last)",
        r.status_code == 409 and r.json()["error"]["code"] == "break_glass_last",
        r.text[:200],
    )

finish()
