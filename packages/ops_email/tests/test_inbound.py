"""Mail in, by failure mode: a redelivery that keys differently, a cursor that moves past mail a poll never handled, a
filter that lets the wrong mail through, and a Graph source that reads the wrong folder or no token."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest

from ops_email import EmailFilter, GraphMailSource, GraphToken, drain, parse_item
from ops_email.testing import FakeMailSource


def item(mid: str | None, *, sender: str = "a@x.example", subject: str = "Hello", **extra: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "from": {"emailAddress": {"address": sender}},
        "subject": subject,
        "receivedDateTime": "2026-10-17T10:00:00Z",
        "body": {"content": "text"},
        **extra,
    }
    if mid is not None:
        d["internetMessageId"] = mid
    return d


def test_a_redelivery_keys_the_same_whatever_its_brackets_or_domain_case() -> None:
    keys = {parse_item(item(m)).key for m in ("<Ab.1@Mail.Example>", "Ab.1@mail.example", " <Ab.1@MAIL.EXAMPLE> ")}
    assert keys == {"Ab.1@mail.example"}
    # The local part is case-sensitive (RFC 5322): another case is another message.
    assert parse_item(item("ab.1@mail.example")).key != "Ab.1@mail.example"


def test_a_message_with_no_message_id_keys_on_sender_time_and_subject() -> None:
    a = parse_item(item(None, sender="A@X.example", subject=" Dispute "))
    basis = "a@x.example|2026-10-17T10:00:00Z|Dispute"
    assert a.key == "synthetic:" + hashlib.sha256(basis.encode()).hexdigest()[:32]
    assert parse_item(item(None, sender="a@x.example", subject="Dispute")).key == a.key


def test_a_removed_item_parses_as_removed() -> None:
    assert parse_item({"id": "m1", "@removed": {"reason": "deleted"}}).removed


async def test_the_cursor_comes_back_only_after_the_last_page_and_a_retry_replays_the_rest() -> None:
    source = FakeMailSource([item(f"m{i}@x") for i in range(5)], page_size=2, fail_once_at=2)
    seen: list[str] = []

    async def handle(raw: dict[str, Any]) -> None:
        seen.append(parse_item(raw).key)

    with pytest.raises(ConnectionError):
        await drain(source, None, handle)
    assert seen == ["m0@x", "m1@x"]  # no cursor was returned, so the caller saved none
    cursor, pages = await drain(source, None, handle)
    assert cursor == "delta:5" and pages == 3
    assert seen[2:] == ["m0@x", "m1@x", "m2@x", "m3@x", "m4@x"]
    source.arrive(item("m5@x"))
    seen.clear()
    assert (await drain(source, cursor, handle))[0] == "delta:6"
    assert seen == ["m5@x"]


@pytest.mark.parametrize(
    ("f", "expected"),
    [
        (EmailFilter(), True),
        (EmailFilter(from_contains="@court.example"), True),
        (EmailFilter(from_contains="@other.example"), False),
        (EmailFilter(subject_contains="garnishment"), True),
        (EmailFilter(subject_contains="refund"), False),
        (EmailFilter(has_attachment=True), True),
    ],
)
def test_the_filter_takes_only_matching_mail(f: EmailFilter, expected: bool) -> None:
    m = parse_item(
        item(
            "x@y",
            sender="Clerk@Court.example",
            subject="Notice of GARNISHMENT",
            attachments=[{"name": "n.pdf", "contentType": "application/pdf", "contentBytes": "JVBE"}],
        )
    )
    assert f.matches(m) is expected


def test_has_attachment_drops_mail_without_one() -> None:
    assert not EmailFilter(has_attachment=True).matches(parse_item(item("x@y")))


async def test_graph_reads_the_named_folder_with_an_app_token_fetched_once() -> None:
    calls: list[httpx.Request] = []

    def route(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200, json={"value": [item("a@b")], "@odata.deltaLink": "https://graph.test/delta?token=1"}
        )

    http = httpx.AsyncClient(base_url="https://graph.test", transport=httpx.MockTransport(route))
    token = GraphToken(
        http,
        login_url="https://login.test",
        tenant="t1",
        client_id="c",
        secret="s",
        scope="https://graph.test/.default",
    )
    source = GraphMailSource(http, token, "levy@bank.example", "Levies")
    page = await source.delta(None)
    await source.delta(page.delta_link)
    paths = [c.url.path for c in calls]
    assert paths[0] == "/t1/oauth2/v2.0/token"
    assert paths[1] == "/v1.0/users/levy@bank.example/mailFolders/Levies/messages/delta"
    assert len([p for p in paths if p.endswith("/token")]) == 1
    assert calls[1].headers["authorization"] == "Bearer tok"
    assert json.loads(json.dumps(page.items))[0]["internetMessageId"] == "a@b"
