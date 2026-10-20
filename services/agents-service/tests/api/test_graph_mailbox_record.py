"""A Microsoft 365 mailbox record (c-228), by failure mode: a mailbox that could not be read is saved; a Graph sender
on a mailbox of another kind is saved; the record or any response carries the client secret's value."""

from __future__ import annotations

from typing import Any

from tests.api.test_channel_mailboxes import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]

M365: dict[str, Any] = {
    "name": "Levy intake (Microsoft 365)",
    "address": "levy@contoso.example",
    "provider": "graph",
    "graphTenantId": "contoso.onmicrosoft.com",
    "graphClientId": "11111111-2222-3333-4444-555555555555",
    "passwordSecret": "M365_CLIENT_SECRET",
    "sender": "graph",
}


async def test_a_microsoft_365_mailbox_is_saved_with_its_registration_by_name(stack: Stack) -> None:  # noqa: F811
    made = await stack.connect(M365)
    assert made.status_code == 201, made.text
    view = made.json()["data"]
    assert (view["graphTenantId"], view["graphClientId"], view["passwordSecret"], view["sender"]) == (
        M365["graphTenantId"],
        M365["graphClientId"],
        "M365_CLIENT_SECRET",
        "graph",
    )


async def test_a_mailbox_that_could_not_be_read_or_reply_is_refused(stack: Stack) -> None:  # noqa: F811
    no_client = await stack.connect({k: v for k, v in M365.items() if k != "graphClientId"})
    assert (no_client.status_code, no_client.json()["error"]["code"]) == (422, "mailbox_incomplete"), no_client.text
    imap_graph_sender = {
        "name": "IMAP",
        "address": "intake@bank.example",
        "provider": "imap",
        "imapHost": "mail.bank.test",
        "passwordSecret": "IMAP_PASSWORD",
        "sender": "graph",
    }
    wrong = await stack.connect(imap_graph_sender)
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (422, "sender_incomplete"), wrong.text
