"""uc-021 sign in, session, refresh, sign out, api layer: docs/usecases/platform-service/sign-in-and-sessions.md."""

from __future__ import annotations

import time

from usecase_harness import check, data, finish, platform

JAMES = {"email": "j.richardson@northfieldbank.com", "password": "northfield-demo"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# Tokens live two seconds here, so one expires inside the run.
with platform(token_ttl_s=2) as (api, _):
    r = api.post("/v1/auth/sign-in", json=JAMES)
    first = data(r) if r.status_code == 200 else {}
    check(
        "sign-in returns a token and a refresh token",
        bool(first.get("token") and first.get("refreshToken")),
        r.text[:200],
    )
    r = api.get("/v1/auth/session", headers=bearer(first.get("token", "")))
    check(
        "the session resolves to James on team_ops",
        r.status_code == 200 and data(r)["roles"] == {"team_ops": "builder"},
        r.text[:200],
    )
    time.sleep(3)
    r = api.get("/v1/auth/session", headers=bearer(first.get("token", "")))
    check("the token is 401 past its TTL", r.status_code == 401, r.status_code)
    r = api.post("/v1/auth/refresh", json={"refreshToken": first.get("refreshToken")})
    second = data(r) if r.status_code == 200 else {}
    fresh = api.get("/v1/auth/session", headers=bearer(second.get("token", "")))
    check("refresh returns a fresh token that resolves", fresh.status_code == 200, r.text[:200])
    # Non-vacuous: the rotated refresh token presented again is theft, so the whole session ends.
    reused = api.post("/v1/auth/refresh", json={"refreshToken": first.get("refreshToken")})
    check("reusing a rotated refresh token is 401", reused.status_code == 401, reused.status_code)
    after = api.get("/v1/auth/session", headers=bearer(second.get("token", "")))
    check("the reuse ended the session for its current token too", after.status_code == 401, after.status_code)

    third = data(api.post("/v1/auth/sign-in", json=JAMES))
    out = api.post("/v1/auth/sign-out", headers=bearer(third["token"]))
    r = api.get("/v1/auth/session", headers=bearer(third["token"]))
    check(
        "after sign-out the token is 401",
        out.status_code == 204 and r.status_code == 401,
        (out.status_code, r.status_code),
    )
    r = api.post("/v1/auth/refresh", json={"refreshToken": third["refreshToken"]})
    check("after sign-out the refresh token is 401", r.status_code == 401, r.status_code)

finish()
