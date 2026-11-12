"""A real SAML identity provider for the sign-in use cases: Keycloak (quay.io/keycloak/keycloak:26.0.7 in Docker),
reached over HTTP like a bank's. The container is started once per machine (`OPS_USECASE_KEYCLOAK_URL`, default
http://127.0.0.1:8780, admin/admin) and this module provisions its realm, groups, users and one SAML client per
provider through Keycloak's admin REST API, so a script needs no hand-made configuration. No secrets are involved."""

from __future__ import annotations

import html
import os
import re
from typing import Any

import httpx

KEYCLOAK = os.environ.get("OPS_USECASE_KEYCLOAK_URL", "http://127.0.0.1:8780").rstrip("/")
REALM = "ops-uc"
PASSWORD = "uc-keycloak-pass"
GROUPS = ("platform-readers", "platform-builders", "other")


class Keycloak:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=KEYCLOAK, timeout=30)
        r = self.http.post(
            "/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin"},
        )
        if r.status_code != 200:
            raise SystemExit(
                f"FAIL Keycloak at {KEYCLOAK} did not give an admin token ({r.status_code}): {r.text[:200]}"
            )
        self.admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
        if self.http.get(f"/admin/realms/{REALM}", headers=self.admin).status_code == 404:
            made = self.http.post(
                "/admin/realms", headers=self.admin, json={"realm": REALM, "enabled": True, "sslRequired": "none"}
            )
            made.raise_for_status()
        for g in GROUPS:
            self.http.post(f"/admin/realms/{REALM}/groups", headers=self.admin, json={"name": g})  # 409 when it exists

    # -- the identity provider as the service provider is told about it
    @property
    def entity_id(self) -> str:
        return f"{KEYCLOAK}/realms/{REALM}"

    @property
    def sso_url(self) -> str:
        return f"{KEYCLOAK}/realms/{REALM}/protocol/saml"

    def certificate(self) -> str:
        xml = self.http.get(f"/realms/{REALM}/protocol/saml/descriptor").text
        body = re.search(r"<(?:\w+:)?X509Certificate>([^<]+)<", xml)
        assert body, "the Keycloak descriptor holds no signing certificate"
        return f"-----BEGIN CERTIFICATE-----\n{body.group(1).strip()}\n-----END CERTIFICATE-----\n"

    # -- provisioning
    def register_sp(self, metadata_xml: str) -> None:
        """A SAML client imported from the service provider's own metadata, sending the person's groups in a `groups`
        attribute and the email as the NameID."""
        base = f"/admin/realms/{REALM}"
        conv = self.http.post(
            f"{base}/client-description-converter",
            headers=self.admin | {"Content-Type": "text/plain"},
            content=metadata_xml,
        )
        conv.raise_for_status()
        client: dict[str, Any] = conv.json()
        client["protocol"] = "saml"
        client["attributes"] = (client.get("attributes") or {}) | {
            "saml_name_id_format": "email",
            "saml_force_name_id_format": "true",
            "saml.force.post.binding": "true",
            "saml.server.signature": "true",
            "saml.client.signature": "false",
        }
        client["protocolMappers"] = [
            {
                "name": "groups",
                "protocol": "saml",
                "protocolMapper": "saml-group-membership-mapper",
                "config": {
                    "attribute.name": "groups",
                    "attribute.nameformat": "Basic",
                    "full.path": "false",
                    "single": "false",
                },
            }
        ]
        made = self.http.post(f"{base}/clients", headers=self.admin, json=client)
        if made.status_code not in (201, 409):
            raise SystemExit(f"FAIL Keycloak refused the SAML client: {made.status_code} {made.text[:300]}")

    def make_user(self, email: str, groups: tuple[str, ...] = ()) -> str:
        base = f"/admin/realms/{REALM}"
        made = self.http.post(
            f"{base}/users",
            headers=self.admin,
            json={
                "username": email,
                "email": email,
                "emailVerified": True,
                "enabled": True,
                "firstName": "Uc",
                "lastName": "User",
                "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
            },
        )
        made.raise_for_status()
        uid = made.headers["location"].rsplit("/", 1)[1]
        self.set_groups(uid, groups)
        return uid

    def set_groups(self, user_id: str, groups: tuple[str, ...]) -> None:
        base = f"/admin/realms/{REALM}"
        known = {g["name"]: g["id"] for g in self.http.get(f"{base}/groups", headers=self.admin).json()}
        mine = {g["name"]: g["id"] for g in self.http.get(f"{base}/users/{user_id}/groups", headers=self.admin).json()}
        for name, gid in mine.items():
            if name not in groups:
                self.http.delete(f"{base}/users/{user_id}/groups/{gid}", headers=self.admin).raise_for_status()
        for name in groups:
            if name not in mine:
                self.http.put(f"{base}/users/{user_id}/groups/{known[name]}", headers=self.admin).raise_for_status()


class _SecureCookiesOverHttp(httpx.BaseTransport):
    """Keycloak marks its session cookies Secure even on http; a browser accepts them from loopback, httpx's jar does
    not, so the flag is dropped on the way in."""

    def __init__(self) -> None:
        self.inner = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        res = self.inner.handle_request(request)
        res.headers = httpx.Headers(
            [
                (k, v.replace(";Secure", "").replace("; Secure", "") if k.lower() == "set-cookie" else v)
                for k, v in res.headers.multi_items()
            ]
        )
        return res


def browser() -> httpx.Client:
    """A person's browser for the identity provider: it keeps Keycloak's session cookies between requests."""
    return httpx.Client(timeout=30, transport=_SecureCookiesOverHttp())


def _page_to_form(page: str) -> str | None:
    """Keycloak's auto-submit SAML form, upper-case attributes and all, as the lower-case form `post_saml_form` reads."""
    action = re.search(r'action="([^"]*)"', page, re.I)
    fields = re.findall(r'name="(SAMLResponse|RelayState)"\s+value="([^"]*)"', page, re.I)
    if not action or not any(k.lower() == "samlresponse" for k, _ in fields):
        return None
    inputs = "".join(
        f'<input name="{"SAMLResponse" if k.lower() == "samlresponse" else "RelayState"}" value="{v}"/>'
        for k, v in fields
    )
    return f'<form action="{action.group(1)}">{inputs}</form>'


def log_in(browser: httpx.Client, redirect_url: str, email: str, password: str = PASSWORD) -> tuple[str | None, str]:
    """What a browser does at Keycloak for the service provider's redirect: opens it and, if asked, types the email
    and password. Returns (the auto-submit form for platform-service or None, a word for what happened: `answered`
    when Keycloak answered from its own session without asking, `asked` after a login, `refused` otherwise)."""
    page = browser.get(redirect_url, follow_redirects=True)
    form = _page_to_form(page.text)
    if form:
        return form, "answered"
    login = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]*)"', page.text) or re.search(
        r'action="([^"]*login-actions/authenticate[^"]*)"', page.text
    )
    if not login:
        return None, "refused: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page.text))[:200]
    sent = browser.post(
        html.unescape(login.group(1)),
        data={"username": email, "password": password, "credentialId": ""},
        follow_redirects=True,
    )
    form = _page_to_form(sent.text)
    return (
        (form, "asked")
        if form
        else (
            None,
            "refused after login: "
            + "|".join(re.findall(r"(?:feedback-text|pf-m-danger|kc-feedback)[^>]*>([^<]{3,120})", sent.text))
            + sent.url.path,
        )
    )
