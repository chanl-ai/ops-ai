"""Certificate and signed-JWT sign-in (c-583), by failure mode: a connection that proves itself with its certificate
is refused for the client secret it does not use, or saved without the signing pair it does; the signed service account
kind is missing from the platform or from the plugin kit; the connection form is not told which fields a choice makes
required, so it lets Save through to the server's refusal; and the signing key reads back."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_plugin_sdk.manifest import SIGN_IN_KINDS
from ops_policy import AesGcmCipher
from ops_service_kit.settings import Settings
from ops_tools.auth import STRATEGIES, Prepared, StrategyInput
from ops_tools.auth.kinds import BY_ID
from ops_tools.auth.tokens import AuthFailed, ClientProof, Tokens
from ops_tools.store.connections import ConnectionStore

from .test_assertion import pair, parts
from .test_auth_strategies import AnyUrl, _connection  # pyright: ignore[reportPrivateUsage]
from .test_connections import admin, client  # noqa: F401  # pyright: ignore[reportUnusedImport]

TOKEN_URL = "https://login.microsoftonline.test/tenant/oauth2/v2.0/token"
BASE = "https://graph.microsoft.test"


async def made(c: httpx.AsyncClient, who: dict[str, str], kind: str) -> dict[str, Any]:
    res = await c.post("/v1/connections", json={"name": "Partner bank API", "authKind": kind}, headers=who)
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def save(
    c: httpx.AsyncClient, who: dict[str, str], conn: dict[str, Any], settings: dict[str, Any], secrets: dict[str, str]
) -> httpx.Response:
    body = {"revision": conn["revision"], "settings": {"baseUrl": BASE, **settings}, "secretValues": secrets}
    return await c.put(f"/v1/connections/{conn['id']}/environments/production", json=body, headers=who)


async def test_a_certificate_client_saves_with_its_signing_pair_and_no_client_secret(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    key_pem, cert_pem, _ = pair()
    conn = await made(client, who, "oauth2_client_credentials")
    settings = {"tokenUrl": TOKEN_URL, "clientId": "ops-ai-acme", "clientAuth": "private_key_jwt"}
    saved = await save(client, who, conn, {**settings, "signingCertificate": cert_pem}, {"signingKey": key_pem})
    assert saved.status_code == 200, saved.text
    assert key_pem not in (await client.get(f"/v1/connections/{conn['id']}", headers=who)).text


async def test_a_certificate_client_without_its_signing_key_is_refused_naming_it(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    _, cert_pem, _ = pair()
    conn = await made(client, who, "oauth2_client_credentials")
    settings = {"tokenUrl": TOKEN_URL, "clientId": "ops-ai-acme", "clientAuth": "private_key_jwt"}
    refused = await save(client, who, conn, {**settings, "signingCertificate": cert_pem}, {})
    assert refused.status_code == 400 and "Signing key" in refused.text, refused.text


async def test_a_signed_service_account_saves_with_its_key(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    key_pem, _, _ = pair()
    conn = await made(client, who, "oauth2_jwt_bearer")
    settings = {"tokenUrl": "https://oauth2.googleapis.test/token", "clientId": "svc@acme.iam.test", "scopeIn": "claim"}
    saved = await save(client, who, conn, {**settings, "scopes": "drive.readonly"}, {"signingKey": key_pem})
    assert saved.status_code == 200, saved.text
    assert "oauth2_jwt_bearer" in SIGN_IN_KINDS and "oauth2_jwt_bearer" in BY_ID


async def test_the_connection_form_is_told_which_fields_a_choice_makes_required(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    rows: list[dict[str, Any]] = (await client.get("/v1/connection-kinds", headers=admin(tenant))).json()["data"][
        "kinds"
    ]
    cc = next(k for k in rows if k["id"] == "oauth2_client_credentials")
    fields: dict[str, dict[str, Any]] = {f["name"]: f for f in cc["fields"]}
    assert "private_key_jwt" in fields["clientAuth"]["choices"]
    assert fields["signingKey"].get("requiredWhen") == {"clientAuth": "private_key_jwt"}, fields["signingKey"]
    assert fields["clientSecret"].get("optionalWhen") == {"clientAuth": "private_key_jwt"}, fields["clientSecret"]


SIGNED_CLIENT = {"tokenUrl": TOKEN_URL, "clientId": "ops-ai-acme", "clientAuth": "private_key_jwt"}


def token_endpoint(seen: list[dict[str, str]]) -> httpx.AsyncClient:
    async def answer(request: httpx.Request) -> httpx.Response:
        seen.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"access_token": f"at-{len(seen)}", "expires_in": 3600})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def tokens_for(engine: AsyncEngine, tenant: str, seen: list[dict[str, str]]) -> tuple[Tokens, str]:
    store = ConnectionStore(engine)
    conn = await _connection(store, tenant)
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    return Tokens(store, cipher, token_endpoint(seen), AnyUrl()), conn  # pyright: ignore[reportArgumentType]


async def test_a_token_request_sends_a_signed_assertion_and_no_client_secret(engine: AsyncEngine, tenant: str) -> None:
    seen: list[dict[str, str]] = []
    tokens, conn = await tokens_for(engine, tenant, seen)
    key_pem, cert_pem, cert = pair()
    proof = ClientProof(secret="never-sent", signing_key=key_pem, signing_certificate=cert_pem)
    got = await tokens.access(tenant, conn, "test", SIGNED_CLIENT, proof, grant="client_credentials")
    assert got.access == "at-1"
    form = seen[0]
    assert form["client_assertion_type"] == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", form
    assert "client_secret" not in form and "never-sent" not in json.dumps(form)
    header, claims, signed, signature = parts(form["client_assertion"])
    cert.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    assert "x5t#S256" in header and (claims["iss"], claims["sub"], claims["aud"]) == ("ops-ai-acme",) * 2 + (TOKEN_URL,)
    # The assertion joins the call's scrub set, as the key already does.
    assert proof.signed == [form["client_assertion"]]


async def test_a_signed_client_with_no_key_is_refused_before_any_request(engine: AsyncEngine, tenant: str) -> None:
    seen: list[dict[str, str]] = []
    tokens, conn = await tokens_for(engine, tenant, seen)
    with pytest.raises(AuthFailed, match="Signing key"):
        await tokens.access(tenant, conn, "test", SIGNED_CLIENT, ClientProof(secret="s"), grant="client_credentials")
    assert seen == []


async def test_a_signed_service_account_asks_with_the_jwt_as_its_grant(engine: AsyncEngine, tenant: str) -> None:
    seen: list[dict[str, str]] = []
    tokens, conn = await tokens_for(engine, tenant, seen)
    key_pem, _, cert = pair()
    google = {
        "tokenUrl": "https://oauth2.googleapis.test/token",
        "clientId": "svc@acme.iam.test",
        "scopes": "drive.readonly",
        "scopeIn": "claim",
    }
    await tokens.access(tenant, conn, "test", google, ClientProof(signing_key=key_pem), grant="jwt_bearer")
    form = seen[0]
    assert set(form) == {"grant_type", "assertion"}, form
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    _, claims, signed, signature = parts(form["assertion"])
    cert.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    assert claims["iss"] == "svc@acme.iam.test" and claims["aud"] == google["tokenUrl"] and "sub" not in claims
    assert claims["scope"] == "drive.readonly"
    docusign = {
        "tokenUrl": "https://account-d.docusign.test/oauth/token",
        "clientId": "integration-key",
        "subject": "user-guid",
        "audience": "account-d.docusign.com",
        "scopes": "signature impersonation",
    }
    seen.clear()
    await tokens.access(tenant, conn, "production", docusign, ClientProof(signing_key=key_pem), grant="jwt_bearer")
    claims = parts(seen[0]["assertion"])[1]
    assert (claims["sub"], claims["aud"]) == ("user-guid", "account-d.docusign.com") and "scope" not in claims
    assert seen[0]["scope"] == "signature impersonation"


async def test_a_call_on_a_signed_service_account_carries_its_token_and_scrubs_the_assertion(
    engine: AsyncEngine, tenant: str
) -> None:
    seen: list[dict[str, str]] = []
    tokens, conn = await tokens_for(engine, tenant, seen)
    key_pem, _, _ = pair()
    settings = {"tokenUrl": TOKEN_URL, "clientId": "svc@acme.iam.test", "scopes": "files.read"}
    i = StrategyInput(tenant, conn, "test", settings, {"signingKey": key_pem}, tokens, None)
    p = Prepared(conn, "test")
    await STRATEGIES["oauth2_jwt_bearer"](i, p)
    assert p.headers["Authorization"] == "Bearer at-1" and p.renewable
    assert seen[0]["assertion"] in p.values and "at-1" in p.values


async def test_a_key_that_is_not_the_certificates_is_refused_at_save_also_when_only_one_half_changes(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    key_pem, cert_pem, _ = pair()
    other_key, other_cert, _ = pair()
    conn = await made(client, who, "oauth2_client_credentials")
    mixed = await save(client, who, conn, {**SIGNED_CLIENT, "signingCertificate": cert_pem}, {"signingKey": other_key})
    assert mixed.status_code == 400 and "Signing key" in mixed.text and "Signing certificate" in mixed.text, mixed.text
    good = await save(client, who, conn, {**SIGNED_CLIENT, "signingCertificate": cert_pem}, {"signingKey": key_pem})
    assert good.status_code == 200, good.text
    # Only the certificate changes: the key held is read and checked against it.
    conn = good.json()["data"]
    swapped = await save(client, who, conn, {**SIGNED_CLIENT, "signingCertificate": other_cert}, {})
    assert swapped.status_code == 400 and "Signing key" in swapped.text, swapped.text
    assert other_key not in swapped.text and key_pem not in swapped.text


async def test_a_read_shows_the_certificates_thumbprint_and_expiry_and_never_the_key(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    who = admin(tenant)
    key_pem, cert_pem, cert = pair(days=10)
    conn = await made(client, who, "oauth2_client_credentials")
    saved = await save(client, who, conn, {**SIGNED_CLIENT, "signingCertificate": cert_pem}, {"signingKey": key_pem})
    assert saved.status_code == 200, saved.text
    read = await client.get(f"/v1/connections/{conn['id']}", headers=who)
    assert key_pem not in read.text
    shown = read.json()["data"]["environments"]["production"]["certificate"]
    assert shown["thumbprint"] == hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(), shown
    assert shown["subject"] == "CN=ops-ai-acme" and shown["expiresSoon"] is True and shown["notAfter"], shown


async def test_an_expired_signing_certificate_is_refused_before_any_request_as_the_systems_side(
    engine: AsyncEngine, tenant: str
) -> None:
    seen: list[dict[str, str]] = []
    tokens, conn = await tokens_for(engine, tenant, seen)
    key_pem, cert_pem, _ = pair(days=-1)
    settings = {**SIGNED_CLIENT, "signingCertificate": cert_pem}
    i = StrategyInput(tenant, conn, "test", settings, {"signingKey": key_pem}, tokens, None)
    with pytest.raises(AuthFailed, match="signing certificate expired on 2026-10-29") as e:
        await STRATEGIES["oauth2_client_credentials"](i, Prepared(conn, "test"))
    assert e.value.side == "upstream" and seen == []


async def test_a_refresh_sends_the_signed_assertion_and_no_client_secret(engine: AsyncEngine, tenant: str) -> None:
    seen: list[dict[str, str]] = []
    tokens, conn = await tokens_for(engine, tenant, seen)
    key_pem, cert_pem, _ = pair()
    # A sign-in whose token is already inside the refresh window.
    await tokens.store_answer(tenant, conn, "test", {"access_token": "at-0", "refresh_token": "rt-0", "expires_in": 5})
    proof = ClientProof(secret="never-sent", signing_key=key_pem, signing_certificate=cert_pem)
    await tokens.access(tenant, conn, "test", SIGNED_CLIENT, proof, grant="none")
    form = seen[0]
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "rt-0", form
    assert form["client_assertion_type"] == "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    assert "client_secret" not in form and proof.signed == [form["client_assertion"]]
