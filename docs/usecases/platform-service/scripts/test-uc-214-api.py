"""uc-214 wrong passwords lock sign-in and step-up, and reset mail is capped, api layer:
docs/usecases/platform-service/wrong-passwords-lock-sign-in.md."""

from __future__ import annotations

import json
import re

from usecase_harness import bearer, check, data, finish, signed_in, signin_stack

LENA, OMAR = "l.fischer@harborpine.example", "o.haddad@harborpine.example"
WRONG, NEW = "not the password at all", "a long new password 3"

with signin_stack() as (api, _, mail):

    def sign_in(email: str, password: str) -> int:
        return api.post("/v1/auth/sign-in", json={"email": email, "password": password}).status_code

    codes = [sign_in(LENA, WRONG) for _ in range(5)]
    check("Lena's first four wrong passwords are 401 and the fifth locks her (429)", codes == [401] * 4 + [429], codes)
    r = api.post("/v1/auth/sign-in", json={"email": LENA, "password": "northfield-demo"})
    check(
        "while locked even her right password is refused with signin_locked and a Retry-After",
        r.status_code == 429
        and r.json()["error"]["code"] == "signin_locked"
        and int(r.headers.get("Retry-After", "0")) > 0,
        r.text[:200],
    )

    omar = signed_in(api, OMAR)
    for _ in range(4):
        sign_in(OMAR, WRONG)
    r = api.post("/v1/auth/step-up", json={"password": WRONG}, headers=bearer(omar))
    check("a wrong step-up counts with Omar's wrong sign-ins and locks him (429)", r.status_code == 429, r.text[:200])

    replies = [api.post("/v1/auth/password/forgot", json={"email": LENA}).status_code for _ in range(4)]
    sent = [json.loads(f.read_text()) for f in sorted(mail.glob("*.json"))]
    to_lena = [m for m in sent if m["to"] == [LENA]]
    check(
        "four reset requests are each answered 204 and only three mails go out",
        replies == [204] * 4 and len(to_lena) == 3,
        replies,
    )
    link = re.search(r"/reset-password/(prt_[A-Za-z0-9_-]+)", to_lena[-1]["body"]) if to_lena else None
    r = api.post("/v1/auth/password/reset", json={"token": link.group(1) if link else "prt_x", "password": NEW})
    check("Lena sets a new password through the link (204)", r.status_code == 204, r.text[:200])
    r = api.post("/v1/auth/sign-in", json={"email": LENA, "password": NEW})
    check(
        "the reset ended her lock: she signs in with the new password",
        r.status_code == 200 and bool(data(r).get("token")),
        r.text[:200],
    )

finish()
