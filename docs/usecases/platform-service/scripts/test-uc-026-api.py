"""uc-026 anonymous and dev boundary, api layer: docs/usecases/platform-service/anonymous-and-dev-boundary.md."""

from __future__ import annotations

import re

from ops_identity import dev_service_signer, mint_service_token
from ops_platform.keys import dev_signer
from ops_policy import mint
from usecase_harness import check, data, finish, platform

PUBLIC = {
    ("GET", "/v1/health"),
    ("GET", "/.well-known/jwks.json"),
    ("POST", "/v1/auth/sign-in"),
    ("POST", "/v1/auth/refresh"),
    ("GET", "/v1/invites/{token}"),
    ("POST", "/v1/invites/{token}/accept"),
}
SAMPLE = {"token": "inv_aaaaaaaaaaaa", "key_id": "key_aaaaaaaa"}

with platform() as (api, _):
    doc = api.get("/openapi.json").json()
    refused = []
    for path, ops in doc["paths"].items():
        for method in ops:
            if (method.upper(), path) in PUBLIC:
                continue
            concrete = re.sub(r"\{([^}]+)\}", lambda m: SAMPLE.get(m.group(1), "x"), path)
            r = api.request(method.upper(), concrete, json={})
            if r.status_code != 401:
                refused.append((method.upper(), path, r.status_code))
    swept = sum(len(ops) for ops in doc["paths"].values()) - len(PUBLIC)
    check(f"all {swept} non-public operations are 401 without credentials", not refused and swept >= 10, refused)

    r = api.get("/v1/me", headers={"X-Dev-User": "j.richardson@northfieldbank.com"})
    check("X-Dev-User grants nothing", r.status_code == 401, r.status_code)

    # Signed with platform's own dev key, so only the audience is wrong.
    james = data(
        api.post("/v1/auth/sign-in", json={"email": "j.richardson@northfieldbank.com", "password": "northfield-demo"})
    )
    claims = {"sub": "usr_builder", "sid": "x", "tenant_id": "local", "team_ids": ["team_ops"], "aud": ["tools"]}
    r = api.get("/v1/auth/session", headers={"Authorization": f"Bearer {mint(claims, dev_signer(), ttl_s=60)}"})
    real = api.get("/v1/auth/session", headers={"Authorization": f"Bearer {james['token']}"})
    check(
        "a token for another service is 401 where the platform's own is 200",
        r.status_code == 401 and real.status_code == 200,
        (r.status_code, real.status_code),
    )

    service = mint_service_token(dev_service_signer(), service="usecases", audience="platform", tenant_id="local")
    r = api.get("/v1/me", headers={"Authorization": f"Bearer {service}"})
    check("a service token on the public mount is 401", r.status_code == 401, r.status_code)

finish()
