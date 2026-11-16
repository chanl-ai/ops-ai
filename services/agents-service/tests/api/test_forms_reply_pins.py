"""Every hosted-form route's reply, status and error code, value by value, by failure mode: a link opened before
sign-in answering more or less than it did, or with another status or code, for a good link, a token that is not one
of ours, a token made for another slug; the builder routes changing a
key; a body field a caller sends being refused or a stray one passing. Regenerate only for an intended change:
`AGENTS_REPIN=1` writes what the routes answer now to `fixtures/reply-pins-forms.json`."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from tests.api.test_forms import OUTSIDER, VALUES, live, shared
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER

from .test_reply_pins import FIXTURES, answer, compare

# A form's slug ends in a generated tail, and an error message names the form's generated id.
_TAILS = re.compile(r"(-[0-9a-f]{6})\b|form_[0-9a-f]{12}|(fk\.[^\"]+)")


def _seen(r: httpx.Response) -> dict[str, Any]:
    out = answer(r)
    return json.loads(
        _TAILS.sub(lambda m: "-<tail>" if m.group(1) else "<token>" if m.group(2) else "<form>", json.dumps(out))
    )


async def test_the_form_routes_keep_every_key_value_and_error_object(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await live(c)
    seen: dict[str, Any] = {}
    form = await shared(c, title="Ask for a payment plan", description="Tell us what has changed.")
    slug, token, fid = form["slug"], form["token"], form["id"]
    seen["create.stray"] = _seen(
        await c.post("/v1/workflows/payment_plan/forms", json={"mode": "members", "colour": "red"}, headers=BUILDER)
    )
    seen["create.badCap"] = _seen(
        await c.post("/v1/workflows/payment_plan/forms", json={"dailyCap": 0}, headers=BUILDER)
    )
    seen["list"] = _seen(await c.get("/v1/workflows/payment_plan/forms", headers=BUILDER))
    seen["update"] = _seen(await c.patch(f"/v1/forms/{fid}", json={"afterText": "Thanks."}, headers=BUILDER))
    seen["update.outsider"] = _seen(await c.patch(f"/v1/forms/{fid}", json={"paused": True}, headers=OUTSIDER))
    seen["update.missing"] = _seen(await c.patch("/v1/forms/form_missing1", json={}, headers=BUILDER))
    public = f"/v1/forms/public/{slug}"
    seen["public"] = _seen(await c.get(public, params={"t": token}))
    seen["public.notOurs"] = _seen(await c.get(public, params={"t": "not-a-token"}))
    seen["public.otherSlug"] = _seen(await c.get("/v1/forms/public/another-form", params={"t": token}))
    seen["submit"] = _seen(await c.post(f"{public}/submit", params={"t": token}, json={"values": VALUES}))
    seen["submit.stray"] = _seen(
        await c.post(f"{public}/submit", params={"t": token}, json={"values": VALUES, "extra": 1})
    )
    seen["files.noFiles"] = _seen(await c.post(f"{public}/files", params={"t": token}, content=b"x"))
    seen["rotate"] = _seen(await c.post(f"/v1/forms/{fid}/rotate", headers=BUILDER))
    seen["public.rotated"] = _seen(await c.get(public, params={"t": token}))
    members = await shared(c, mode="members", title="Members only")
    seen["members"] = _seen(await c.get(f"/v1/forms/{members['slug']}/members", headers=BUILDER))
    seen["members.outsider"] = _seen(await c.get(f"/v1/forms/{members['slug']}/members", headers=OUTSIDER))
    compare(seen, FIXTURES / "reply-pins-forms.json")
