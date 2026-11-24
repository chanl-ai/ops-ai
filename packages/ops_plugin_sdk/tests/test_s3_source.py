"""The Amazon S3 plugin against a real S3-compatible store, by failure mode: a listing that stops after one page, a
fetch of an object whose ETag still matches, and the knowledge-source contract kb-service and Files rely on.

The store is the one `OPS_TEST_S3_URL` names, with the key `OPS_TEST_S3_KEY` and secret `OPS_TEST_S3_SECRET`
(SeaweedFS in Docker answers the S3 API, started with
`docker run -p 127.0.0.1:19000:8333 chrislusf/seaweedfs server -s3 -s3.config=<ids.json> -volume.max=0`).
Every request is signed with AWS Signature Version 4, as tools-service signs it, so the store checks each signature.
Without the variables the tests are skipped."""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from ops_plugin_sdk import Plugin
from ops_plugin_sdk.testing import Fake, call, knowledge_contract

URL, KEY, SECRET = (os.environ.get(n, "") for n in ("OPS_TEST_S3_URL", "OPS_TEST_S3_KEY", "OPS_TEST_S3_SECRET"))
REGION = "us-east-1"
# CI starts the store and sets the variables, so a run there that would skip fails instead.
pytestmark = pytest.mark.skipif(not URL and not os.environ.get("CI"), reason="no S3 store named in OPS_TEST_S3_URL")
PLUGINS = Path(__file__).resolve().parents[3] / "builtin-plugins"
sys.path.insert(0, str(PLUGINS))


class Signed(httpx.Auth):
    """Signs each request as tools-service's aws_sigv4 kind does, replacing the test kit's bearer header."""

    def __init__(self, key: str, secret: str) -> None:
        self.signer = SigV4Auth(Credentials(key, secret), "s3", REGION)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        request.headers.pop("Authorization", None)
        asked = AWSRequest(
            method=request.method, url=str(request.url), data=request.content, headers=dict(request.headers)
        )
        asked.headers["X-Amz-Content-SHA256"] = self.signer.payload(asked)
        self.signer.add_auth(asked)
        for h in ("Authorization", "X-Amz-Date", "X-Amz-Content-SHA256"):
            request.headers[h] = asked.headers[h]
        yield request


def store(secret: str = SECRET) -> httpx.Client:
    return httpx.Client(auth=Signed(KEY, secret), timeout=30)


@pytest.fixture
def bucket() -> Iterator[str]:
    assert URL, "CI names an S3 store in OPS_TEST_S3_URL (make s3-test-store); these tests do not skip there"
    name = f"s3test-{uuid.uuid4().hex[:10]}"
    with store() as s:
        assert s.put(f"{URL}/{name}").status_code == 200
        yield name
        listed = s.get(f"{URL}/{name}", params={"list-type": "2"}).text
        for key in [p.split("</Key>")[0] for p in listed.split("<Key>")[1:]]:
            s.delete(f"{URL}/{name}/{key}")
        s.delete(f"{URL}/{name}")


def put(bucket: str, key: str, body: bytes) -> str:
    with store() as s:
        assert s.put(f"{URL}/{bucket}/{key}", content=body).status_code == 200
    return f"{bucket}/{key}"


def s3() -> Plugin:
    return Plugin.beside(str(PLUGINS / "ops_plugin_s3/__init__.py"))


SETTINGS = {"endpoint_url": URL}


def test_a_listing_over_three_pages_finds_every_object_and_an_unchanged_etag_fetches_nothing(
    bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.import_module("ops_plugin_s3.files"), "PAGE", 2)
    ids = {put(bucket, f"Invoices/2026-12/inv-{n}.pdf", f"%PDF invoice {n}".encode()) for n in range(5)}
    put(bucket, "Elsewhere/skip.txt", b"not picked")
    fake = Fake(store(), "unused")
    source = {"folders": [f"{bucket}/Invoices/"]}
    seen: list[str] = []
    cursor: Any = None
    pages = 0
    while pages < 10:
        page = call(s3(), "list_files", {"source": source, **({"cursor": cursor} if cursor else {})}, SETTINGS, fake)
        pages += 1
        seen += [r["id"] for r in page["items"]]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    assert (pages, set(seen)) == (3, ids)
    one = sorted(ids)[0]
    got = call(s3(), "get_file", {"source": source, "id": one}, SETTINGS, fake)
    assert got["encoding"] == "base64" and got["marker"]
    again = call(s3(), "get_file", {"source": source, "id": one, "tag": got["marker"]}, SETTINGS, fake)
    assert again == {"unchanged": True}


def test_the_s3_source_keeps_the_knowledge_contract(bucket: str) -> None:
    for n in range(3):
        put(bucket, f"Claims/claim-{n}.txt", f"claim {n}".encode())

    def change() -> str:
        return put(bucket, "Claims/claim-1.txt", b"claim 1, amended")

    def delete() -> str:
        with store() as s:
            s.delete(f"{URL}/{bucket}/Claims/claim-2.txt")
        return f"{bucket}/Claims/claim-2.txt"

    problems = knowledge_contract(
        s3(), "files", Fake(store(), "unused"), settings=SETTINGS, values={"folders": [f"{bucket}/Claims/"]},
        change=change, delete=delete,
    )  # fmt: skip
    assert problems == []


def test_a_wrong_secret_is_refused_in_plain_words_and_never_echoed(bucket: str) -> None:
    put(bucket, "a.txt", b"a")
    with pytest.raises(Exception) as refused:
        call(
            s3(), "list_files", {"source": {"folders": [f"{bucket}/"]}}, SETTINGS, Fake(store("wrong-secret-xyz"), "x")
        )
    assert "key or its secret is wrong" in str(refused.value) and "wrong-secret-xyz" not in str(refused.value)
