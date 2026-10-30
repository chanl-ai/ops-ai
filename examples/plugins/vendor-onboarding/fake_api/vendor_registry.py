"""A fake company registry for the vendor-onboarding example: the outside system the vendor-registry module calls.

    uv run python examples/plugins/vendor-onboarding/fake_api/vendor_registry.py      serves it on http://127.0.0.1:8790

Two routes, the two operations in contributions/tool-modules/vendor-registry/module.yaml:
    GET  /v1/companies/{registration_number}   the company's record, 404 when the registry has none
    POST /v1/screenings {name, country}         sanctions hits for a name, [] when none
Every call needs `X-Api-Key: dev-registry-key` (FAKE_REGISTRY_KEY), as the module's `{{VENDOR_REGISTRY_KEY}}` header
sends it.

tools-service reaches outside systems over https on port 443 only, by a host on the team's egress list, so a local
stack cannot call this server as it is served here; test runs answer from the module's mocks instead, and
tests/test_fake_api.py keeps those mocks equal to what this server answers. See the README, "Gaps found".
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

KEY = os.environ.get("FAKE_REGISTRY_KEY", "dev-registry-key")

COMPANIES: dict[str, dict[str, Any]] = {
    "RC-1048213": {
        "registrationNumber": "RC-1048213",
        "legalName": "Brightwater Logistics Ltd.",
        "country": "CA",
        "status": "active",
        "yearsTrading": 3,
    },
    "RC-0000017": {
        "registrationNumber": "RC-0000017",
        "legalName": "Old Quay Traders Ltd",
        "country": "GB",
        "status": "dissolved",
        "yearsTrading": 12,
    },
}
SANCTIONED = {"sable freight partners": "Consolidated sanctions list"}

app = FastAPI(title="Fake vendor registry", version="1.0.0")


def _key(x_api_key: str | None) -> None:
    if x_api_key != KEY:
        raise HTTPException(status_code=401, detail="Send X-Api-Key.")


@app.get("/v1/companies/{registration_number}")
def lookup_company(registration_number: str, x_api_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    _key(x_api_key)
    company = COMPANIES.get(registration_number)
    if company is None:
        raise HTTPException(status_code=404, detail=f"No company {registration_number}.")
    return company


class Screening(BaseModel):
    name: str
    country: str = ""


@app.post("/v1/screenings")
def screen_vendor(body: Screening, x_api_key: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    _key(x_api_key)
    listed = SANCTIONED.get(body.name.strip().lower())
    hits = [{"list": listed, "name": body.name, "score": 0.97}] if listed else []
    return {"hits": hits}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FAKE_REGISTRY_PORT", "8790")))
