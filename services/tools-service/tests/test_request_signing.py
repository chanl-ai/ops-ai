"""A sign-in kind that signs each request (aws_sigv4), by failure mode: one signature reused for a second request (the
next page, another path) that the store refuses; a wrong secret that is not refused in plain words, or whose value
reaches the answer or the log.

The Amazon S3 plugin runs through the gateway's plugin executor against the S3-compatible store `OPS_TEST_S3_URL`
names (SeaweedFS in Docker, as test_s3_source.py says), which checks every
signature. Only the account lookup is stood in for: the real strategy
prepares the call and the executor signs each request. Skipped without the store."""

from __future__ import annotations

import importlib
import logging
import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_plugin_sdk import Plugin
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.http import Json
from ops_tools.auth import STRATEGIES, Prepared, StrategyInput
from ops_tools.executor import HttpExecutor
from ops_tools.plugins.executor import PluginExecutor
from ops_tools.plugins.host import PluginHost
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import Module, ModuleStore, Operation
from ops_tools.store.plugin_bindings import PluginBindings

from .test_plugins import AllowAll

URL, KEY, SECRET = (os.environ.get(n, "") for n in ("OPS_TEST_S3_URL", "OPS_TEST_S3_KEY", "OPS_TEST_S3_SECRET"))
pytestmark = pytest.mark.skipif(not URL, reason="no S3-compatible store named in OPS_TEST_S3_URL")
PLUGINS = Path(__file__).resolve().parents[3] / "builtin-plugins"
sys.path.insert(0, str(PLUGINS))
S3 = Plugin.beside(str(PLUGINS / "ops_plugin_s3/__init__.py"))


class OneAccount:
    """The account lookup, stood in: an aws_sigv4 account with this secret, prepared by the real strategy."""

    def __init__(self, secret: str) -> None:
        self.secret = secret

    async def prepare(self, module: Any, environment: str, **_: Any) -> Prepared:
        prepared = Prepared("con_s3", values=[self.secret])
        given = StrategyInput(
            str(module["tenant_id"]), "con_s3", {"accessKeyId": KEY, "region": "us-east-1"},
            {"secretAccessKey": self.secret}, None, None,  # type: ignore[arg-type]
        )  # fmt: skip
        await STRATEGIES["aws_sigv4"](given, prepared)
        return prepared


@pytest.fixture
def bucket() -> Iterator[str]:
    import boto3  # noqa: PLC0415

    s3: Any = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3", endpoint_url=URL, aws_access_key_id=KEY, aws_secret_access_key=SECRET, region_name="us-east-1"
    )
    name = f"c967-{uuid.uuid4().hex[:10]}"
    s3.create_bucket(Bucket=name)
    for n in range(3):
        s3.put_object(Bucket=name, Key=f"Invoices/inv-{n}.txt", Body=f"invoice {n}".encode())
    yield name
    for n in range(3):
        s3.delete_object(Bucket=name, Key=f"Invoices/inv-{n}.txt")
    s3.delete_bucket(Bucket=name)


def executor(engine: AsyncEngine, store: ModuleStore, secret: str) -> PluginExecutor:
    host = PluginHost(
        store, PluginBindings(engine), {"opsai.s3": {}}, [Loaded("s3", S3, None)],
        ConnectionStore(engine),
    )  # fmt: skip
    http = HttpExecutor(httpx.AsyncClient(), AllowAll(), None, OneAccount(secret))  # type: ignore[arg-type]
    return PluginExecutor(host, http, b"k" * 32)


def module(tenant: str) -> Module:
    made = {
        "tenant_id": tenant, "id": "mod_plugin_s3", "display_name": "Amazon S3", "template_id": "plugin:opsai.s3",
        "connection_id": "con_s3", "endpoint": URL, "egress_hosts": ["127.0.0.1"],
        "plugin_settings": {"endpoint_url": URL},
    }  # fmt: skip
    return cast(Module, made)


async def run(ex: PluginExecutor, tenant: str, tool: str, args: dict[str, Any]) -> Any:
    op = cast(Operation, {"name": tool})
    return await ex.run(module(tenant), op, cast(Json, args), actor="t", environment="test", acting_for=None)


async def test_each_request_is_signed_and_a_wrong_secret_is_refused_with_no_secret_in_the_answer_or_log(
    *, engine: AsyncEngine, store: ModuleStore, tenant: str, bucket: str, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    monkeypatch.setattr(importlib.import_module("ops_plugin_s3.files"), "PAGE", 2)
    args = {"source": {"folders": [f"{bucket}/Invoices/"]}}
    ex = executor(engine, store, SECRET)
    first = await run(ex, tenant, "list_files", args)
    assert first.ok and first.output["next_cursor"], first
    nxt = {**args, "cursor": first.output["next_cursor"]}
    second = await run(ex, tenant, "list_files", nxt)
    got = await run(ex, tenant, "get_file", {**args, "id": f"{bucket}/Invoices/inv-0.txt"})
    assert second.ok and len(first.output["items"]) + len(second.output["items"]) == 3, second
    assert got.ok and got.output["content"] == "invoice 0", got
    wrong = "not-the-secret-4f2a"
    caplog.set_level(logging.DEBUG)
    refused = await run(executor(engine, store, wrong), tenant, "list_files", args)
    assert not refused.ok and "secret is wrong" in str(refused.output), refused
    assert wrong not in str(refused.output) and wrong not in caplog.text
