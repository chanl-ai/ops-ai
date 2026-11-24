"""AWS Signature Version 4 for the `aws_sigv4` sign-in kind (Amazon S3 and every store that answers its API).

Each request is signed on its own, over its final method, address, headers and body, so a request a tool builds after
another (the next page, a file's bytes) carries its own signature, and a signature never travels to another path. The
signature is botocore's (`SigV4Auth`); the secret stays in this module's closure and in `Prepared.values`, which the
gateway scrubs from everything it returns."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

# The headers a signature adds: what the executor puts on the request it sends.
SIGNED_HEADERS = ("Authorization", "X-Amz-Date", "X-Amz-Content-SHA256", "X-Amz-Security-Token")
Signer = Callable[[str, str, Mapping[str, str], bytes], dict[str, str]]


def sign(
    method: str, url: str, headers: Mapping[str, str], body: bytes, *, key: str, secret: str, region: str, service: str
) -> dict[str, str]:
    """The headers that sign this one request: Authorization, X-Amz-Date and the body's digest."""
    request = AWSRequest(method=method, url=url, data=body, headers=dict(headers))
    signer = SigV4Auth(Credentials(key, secret), service, region)
    # S3 refuses a request whose body digest it cannot match; the digest of the exact bytes sent is always accepted.
    request.headers["X-Amz-Content-SHA256"] = signer.payload(request)
    signer.add_auth(request)
    return {h: str(request.headers[h]) for h in SIGNED_HEADERS if h in request.headers}


def signer_for(*, key: str, secret: str, region: str, service: str) -> Signer:
    def signed(method: str, url: str, headers: Mapping[str, str], body: bytes) -> dict[str, str]:
        return sign(method, url, headers, body, key=key, secret=secret, region=region, service=service)

    return signed


__all__ = ["SIGNED_HEADERS", "Signer", "sign", "signer_for"]
