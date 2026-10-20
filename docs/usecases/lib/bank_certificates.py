"""Certificates for the bank stand-in's certificate-only listener (c-330): a CA of its own, a server certificate for
`mtls.bank.test` and a client certificate the listener accepts, all signed by that CA.

The CA is not the one tools-service trusts for `api.bank.test` (OPS_EGRESS_CA_FILE): a connection names it as its
trusted server certificate, which is how a bank's internal CA reaches the gateway.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

MTLS_HOST = "mtls.bank.test"


def _key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _pem_key(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _signed(
    subject: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: x509.Name,
    signer: ec.EllipticCurvePrivateKey,
    *,
    server: bool,
) -> x509.Certificate:
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
    )
    if server:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(subject)]), critical=False)
    return builder.sign(signer, hashes.SHA256())


def make(folder: Path) -> dict[str, Path]:
    """Writes ca.crt, server.crt, server.key, client.crt and client.key into `folder` and returns their paths."""
    ca_key = _key()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Bank stand-in internal CA")])
    now = datetime.now(UTC)
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key, client_key = _key(), _key()
    server = _signed(MTLS_HOST, server_key, ca_name, ca_key, server=True)
    client = _signed("ops-ai-gateway", client_key, ca_name, ca_key, server=False)
    files = {
        "ca": (folder / "mtls-ca.crt", ca.public_bytes(serialization.Encoding.PEM)),
        "server_cert": (folder / "mtls-server.crt", server.public_bytes(serialization.Encoding.PEM)),
        "server_key": (folder / "mtls-server.key", _pem_key(server_key)),
        "client_cert": (folder / "mtls-client.crt", client.public_bytes(serialization.Encoding.PEM)),
        "client_key": (folder / "mtls-client.key", _pem_key(client_key)),
    }
    for path, body in files.values():
        path.write_bytes(body)
    return {name: path for name, (path, _) in files.items()}
