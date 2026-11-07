"""A person's sign-in request, by failure mode: it does not say whether the call reads or changes something, or which
app it is for, so the chat says "records your name on the change" for a read and names the account, not the app."""

from __future__ import annotations

from ops_tools.auth import AuthFailed
from ops_tools.executor import with_access


def test_a_sign_in_request_names_the_app_and_whether_the_call_reads_or_writes() -> None:
    read = with_access(
        AuthFailed("CONNECTION_NOT_LINKED", "x", details={}), {"access": "read"}, {"display_name": "Salesforce"}
    )
    write = with_access(
        AuthFailed("CONNECTION_NOT_LINKED", "x", details={}), {"access": "write"}, {"display_name": "Salesforce"}
    )
    assert (read.details, write.details["access"]) == ({"access": "read", "app": "Salesforce"}, "write")
    other = with_access(AuthFailed("CONNECTION_REVOKED", "x"), {"access": "write"}, {"display_name": "Salesforce"})
    assert other.details == {}
