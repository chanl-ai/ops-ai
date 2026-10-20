"""Reading an XML Encryption 1.1 element (an `EncryptedAssertion`) with the service provider's private key: the
content key comes from an `EncryptedKey` by RSA-OAEP, and the content from AES-GCM or AES-CBC. Only the algorithms
named below are read; any other, `rsa-1_5` key transport included, is refused by name before anything is decrypted.

Every failure past that point raises the same `DecryptionRefused`, with no detail of what went wrong: a padding error
on CBC that read differently from a bad key would let a sender learn the plaintext a byte at a time. Decryption proves
nothing about who sent the content; the caller still checks a signature.
"""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lxml import etree
from lxml.etree import _Element as Element  # pyright: ignore[reportPrivateUsage]

XENC = "http://www.w3.org/2001/04/xmlenc#"
XENC11 = "http://www.w3.org/2009/xmlenc11#"
DS = "http://www.w3.org/2000/09/xmldsig#"
NS = {"xenc": XENC, "xenc11": XENC11, "ds": DS}

# Content ciphers: (mode, key bytes).
CIPHERS = {
    f"{XENC}aes128-cbc": ("cbc", 16),
    f"{XENC}aes256-cbc": ("cbc", 32),
    f"{XENC11}aes128-gcm": ("gcm", 16),
    f"{XENC11}aes256-gcm": ("gcm", 32),
}
OAEP_MGF1P = f"{XENC}rsa-oaep-mgf1p"
OAEP = f"{XENC11}rsa-oaep"
DIGESTS: dict[str, type[hashes.HashAlgorithm]] = {
    f"{DS}sha1": hashes.SHA1,
    f"{XENC}sha256": hashes.SHA256,
    f"{XENC}sha512": hashes.SHA512,
}
MGFS: dict[str, type[hashes.HashAlgorithm]] = {
    f"{XENC11}mgf1sha1": hashes.SHA1,
    f"{XENC11}mgf1sha256": hashes.SHA256,
    f"{XENC11}mgf1sha512": hashes.SHA512,
}


class DecryptionRefused(Exception):
    """The element could not be read. One reason for every cause, on purpose."""


class UnsupportedAlgorithm(Exception):
    """An algorithm this reader does not take, named so the operator can ask the bank to change it."""


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def _cipher_value(el: Element | None) -> bytes:
    value = el.find("xenc:CipherData/xenc:CipherValue", NS) if el is not None else None
    if value is None or not (value.text or "").strip():
        raise DecryptionRefused
    return base64.b64decode("".join((value.text or "").split()), validate=True)


def check_algorithms(encrypted: Element) -> None:
    """Refuses, by name, a content cipher or key transport this reader does not take. Runs before any decryption."""
    data = encrypted.find("xenc:EncryptedData", NS)
    method = data.find("xenc:EncryptionMethod", NS) if data is not None else None
    content = method.get("Algorithm") if method is not None else None
    if content not in CIPHERS:
        raise UnsupportedAlgorithm(f"content cipher {content}")
    key = _encrypted_key(encrypted, data)
    transport = key.find("xenc:EncryptionMethod", NS)
    algorithm = transport.get("Algorithm") if transport is not None else None
    if algorithm not in (OAEP_MGF1P, OAEP):
        raise UnsupportedAlgorithm(f"key transport {algorithm}")


def _encrypted_key(encrypted: Element, data: Element | None) -> Element:
    # Inside EncryptedData's KeyInfo, or beside EncryptedData in the EncryptedAssertion; both are in use.
    found = data.find("ds:KeyInfo/xenc:EncryptedKey", NS) if data is not None else None
    if found is None:
        found = encrypted.find("xenc:EncryptedKey", NS)
    if found is None:
        raise UnsupportedAlgorithm("no EncryptedKey")
    return found


def decrypt(encrypted: Element, private_key_pem: str) -> bytes:
    """The plaintext of `encrypted` (an element holding one `EncryptedData`). Call `check_algorithms` first."""
    try:
        data = encrypted.find("xenc:EncryptedData", NS)
        if data is None:
            raise DecryptionRefused
        mode, size = CIPHERS[str(data.find("xenc:EncryptionMethod", NS).get("Algorithm"))]  # type: ignore[union-attr]
        ek = _encrypted_key(encrypted, data)
        transport = ek.find("xenc:EncryptionMethod", NS)
        assert transport is not None
        digest_el = transport.find("ds:DigestMethod", NS)
        digest = DIGESTS[digest_el.get("Algorithm", "")] if digest_el is not None else hashes.SHA1
        mgf = hashes.SHA1
        if transport.get("Algorithm") == OAEP:
            mgf_el = transport.find("xenc11:MGF", NS)
            mgf = MGFS[mgf_el.get("Algorithm", "")] if mgf_el is not None else hashes.SHA1
        key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise DecryptionRefused
        content_key = key.decrypt(
            _cipher_value(ek), padding.OAEP(mgf=padding.MGF1(mgf()), algorithm=digest(), label=None)
        )
        if len(content_key) != size:
            raise DecryptionRefused
        blob = _cipher_value(data)
        if mode == "gcm":
            return AESGCM(content_key).decrypt(blob[:12], blob[12:], None)
        iv, body = blob[:16], blob[16:]
        if not body or len(body) % 16:
            raise DecryptionRefused
        decryptor = Cipher(algorithms.AES(content_key), modes.CBC(iv)).decryptor()
        plain = decryptor.update(body) + decryptor.finalize()
        pad = plain[-1]
        if not 1 <= pad <= 16:
            raise DecryptionRefused
        return plain[:-pad]
    except DecryptionRefused:
        raise
    except (ValueError, KeyError, TypeError, AssertionError, InvalidTag, AttributeError) as e:
        raise DecryptionRefused from e


def parse(plaintext: bytes) -> Element:
    try:
        return etree.fromstring(plaintext, parser=_parser())
    except etree.XMLSyntaxError as e:
        raise DecryptionRefused from e
