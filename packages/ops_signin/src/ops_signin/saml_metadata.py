"""An identity provider's SAML metadata, read: its entity id, its sign-in URL on the redirect binding, and every
signing certificate it lists with its dates (SAML metadata 2.4.3).

The document comes from a URL or a file an admin gave, so it is parsed as the responses are: no entities, no network,
no huge trees, 256 KB at most. Nothing here is trusted until an admin saves it; a daily refresh adds certificates only
for the entity id already saved (the caller's rule).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from lxml import etree

from .saml import DSIG, MAX_RESPONSE_BYTES, METADATA

REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
_NS = {"md": METADATA, "ds": DSIG}


class MetadataRefused(ValueError):
    """The document is not usable SAML identity-provider metadata. `code` names why, for the API's error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MetadataCertificate:
    pem: str
    # SHA-256 of the DER bytes, lower-case hex: the key a certificate is stored and compared by.
    fingerprint: str
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True)
class IdpMetadata:
    entity_id: str
    sso_url: str
    certificates: tuple[MetadataCertificate, ...]


def certificate_of(pem_or_base64: str) -> MetadataCertificate:
    """A certificate from PEM or from the bare base64 metadata carries. Raises MetadataRefused."""
    text = pem_or_base64.strip()
    try:
        if "BEGIN CERTIFICATE" in text:
            cert = x509.load_pem_x509_certificate(text.encode())
        else:
            cert = x509.load_der_x509_certificate(base64.b64decode("".join(text.split()), validate=True))
    except ValueError as e:
        raise MetadataRefused("certificate", "A certificate is not an X.509 certificate.") from e
    der = cert.public_bytes(serialization.Encoding.DER)
    return MetadataCertificate(
        pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        fingerprint=hashlib.sha256(der).hexdigest(),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
    )


def read_metadata(document: bytes) -> IdpMetadata:
    """The identity provider in `document`. Raises MetadataRefused with code `metadata_too_large`,
    `metadata_unreadable` (not XML, or not an IdP entity with a redirect sign-in URL) or `metadata_no_certificate`."""
    if len(document) > MAX_RESPONSE_BYTES:
        raise MetadataRefused("metadata_too_large", "The metadata is larger than 256 KB.")
    try:
        root = etree.fromstring(document, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        raise MetadataRefused("metadata_unreadable", "This is not XML.") from e
    entity = root if root.tag == f"{{{METADATA}}}EntityDescriptor" else root.find("md:EntityDescriptor", _NS)
    idp = entity.find("md:IDPSSODescriptor", _NS) if entity is not None else None
    if entity is None or idp is None or not entity.get("entityID"):
        raise MetadataRefused("metadata_unreadable", "This is not a SAML identity provider's metadata.")
    sso = next(
        (
            str(s.get("Location"))
            for s in idp.findall("md:SingleSignOnService", _NS)
            if s.get("Binding") == REDIRECT_BINDING and s.get("Location")
        ),
        None,
    )
    if sso is None:
        raise MetadataRefused("metadata_unreadable", "The metadata names no sign-in URL on the redirect binding.")
    found: dict[str, MetadataCertificate] = {}
    for key in idp.findall("md:KeyDescriptor", _NS):
        # A key with no `use` is for both signing and encryption.
        if key.get("use") not in (None, "signing"):
            continue
        for value in key.findall("ds:KeyInfo/ds:X509Data/ds:X509Certificate", _NS):
            cert = certificate_of("".join(value.itertext()))
            found.setdefault(cert.fingerprint, cert)
    if not found:
        raise MetadataRefused("metadata_no_certificate", "The metadata lists no signing certificate.")
    return IdpMetadata(str(entity.get("entityID")), sso, tuple(found.values()))
