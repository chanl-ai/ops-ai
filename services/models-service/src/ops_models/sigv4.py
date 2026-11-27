"""AWS Signature Version 4 for the requests models-service sends to Amazon Bedrock with an access key pair: the
headers one request needs, computed from its method, URL, body and time. AWS's published algorithm
(docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html), kept here so the service takes
no AWS SDK for two calls. Not yet checked against a real account (**unverified**)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def signed_headers(
    method: str,
    url: str,
    payload: bytes,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    now: datetime | None = None,
) -> dict[str, str]:
    """`host`, `x-amz-date`, `x-amz-content-sha256` and `authorization` for the request."""
    at = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    day = at[:8]
    parts = urlsplit(url)
    body_hash = hashlib.sha256(payload).hexdigest()
    headers = {"host": parts.netloc, "x-amz-content-sha256": body_hash, "x-amz-date": at}
    pairs = sorted(p.split("=", 1) if "=" in p else [p, ""] for p in parts.query.split("&") if p)
    query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs)
    names = ";".join(sorted(headers))
    canonical = "\n".join(
        [
            method,
            quote(parts.path or "/", safe="/-_.~"),
            query,
            "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)),
            names,
            body_hash,
        ]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", at, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={names}, Signature={signature}"
    )
    return headers
