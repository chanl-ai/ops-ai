"""XML Encryption as a bank's identity provider writes it, for the fake identity provider: an `EncryptedAssertion`
holding `EncryptedData` with the content key in an `EncryptedKey` inside its KeyInfo. Tests and the dev stack only.
`key_transport="rsa-1_5"` writes the old transport a service must refuse."""

from __future__ import annotations

import base64
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lxml import etree
from lxml.etree import _Element as Element  # pyright: ignore[reportPrivateUsage]

ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"
XENC = "http://www.w3.org/2001/04/xmlenc#"
XENC11 = "http://www.w3.org/2009/xmlenc11#"
DS = "http://www.w3.org/2000/09/xmldsig#"
CIPHERS = {
    "aes128-cbc": (f"{XENC}aes128-cbc", 16),
    "aes256-cbc": (f"{XENC}aes256-cbc", 32),
    "aes128-gcm": (f"{XENC11}aes128-gcm", 16),
    "aes256-gcm": (f"{XENC11}aes256-gcm", 32),
}


def encrypt_assertion(
    assertion: Element, certificate_pem: str, *, cipher: str = "aes256-gcm", key_transport: str = "rsa-oaep-mgf1p"
) -> Element:
    uri, size = CIPHERS[cipher]
    plaintext = etree.tostring(assertion)
    key = os.urandom(size)
    if cipher.endswith("gcm"):
        nonce = os.urandom(12)
        blob = nonce + AESGCM(key).encrypt(nonce, plaintext, None)
    else:
        iv = os.urandom(16)
        pad = 16 - len(plaintext) % 16
        padded = plaintext + os.urandom(pad - 1) + bytes([pad])
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        blob = iv + encryptor.update(padded) + encryptor.finalize()
    public = x509.load_pem_x509_certificate(certificate_pem.encode()).public_key()
    assert isinstance(public, rsa.RSAPublicKey)
    if key_transport == "rsa-1_5":
        wrapped = public.encrypt(key, padding.PKCS1v15())
    else:
        wrapped = public.encrypt(
            key, padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
        )
    out = etree.Element(f"{{{ASSERTION}}}EncryptedAssertion", nsmap={"saml": ASSERTION})
    data = etree.SubElement(out, f"{{{XENC}}}EncryptedData", nsmap={"xenc": XENC, "ds": DS}, Type=f"{XENC}Element")
    etree.SubElement(data, f"{{{XENC}}}EncryptionMethod", Algorithm=uri)
    info = etree.SubElement(data, f"{{{DS}}}KeyInfo")
    ek = etree.SubElement(info, f"{{{XENC}}}EncryptedKey")
    method = etree.SubElement(ek, f"{{{XENC}}}EncryptionMethod", Algorithm=f"{XENC}{key_transport}")
    if key_transport != "rsa-1_5":
        etree.SubElement(method, f"{{{DS}}}DigestMethod", Algorithm=f"{DS}sha1")
    etree.SubElement(etree.SubElement(ek, f"{{{XENC}}}CipherData"), f"{{{XENC}}}CipherValue").text = base64.b64encode(
        wrapped
    ).decode()
    etree.SubElement(etree.SubElement(data, f"{{{XENC}}}CipherData"), f"{{{XENC}}}CipherValue").text = base64.b64encode(
        blob
    ).decode()
    return out
