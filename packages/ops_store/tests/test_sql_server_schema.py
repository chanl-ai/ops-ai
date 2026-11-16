"""A service's tests on SQL Server get the schema a DBA installs, by failure mode: the test database skips the
preconditions a deployment's install runs, so a test passes on a database an install refuses; the install makes or
changes a server login, which is server-wide and shared by other runs; the chain's runtime and system users are
missing, so a system transaction (EXECUTE AS USER) fails only on SQL Server; another chain's tables come along."""

from __future__ import annotations

from ops_store.schema import MSSQL_COLLATION, MSSQL_PRECONDITIONS
from ops_store.testing import golden_bundle, sql_server_schema


def test_the_bundle_is_the_preconditions_then_the_chain_and_its_grants_with_no_login() -> None:
    batches = golden_bundle("files")
    assert batches[: len(MSSQL_PRECONDITIONS)] == MSSQL_PRECONDITIONS, "the install's preconditions are not run first"
    assert MSSQL_PRECONDITIONS[1].count(MSSQL_COLLATION) == 2, "the collation checked is not the one databases get"
    text = "\n".join(batches)
    assert "CREATE TABLE files" in text and "INSERT INTO alembic_version_files" in text
    assert "LOGIN" not in text.replace("WITHOUT LOGIN", ""), "the install makes, changes or uses a server login"
    assert "CREATE USER ops_files_runtime WITHOUT LOGIN" in text
    assert "GRANT IMPERSONATE ON USER::ops_files_system TO ops_files_runtime" in text
    assert "ops_documents_runtime" not in text and "CREATE TABLE documents" not in text, "another chain came along"
    assert all(b.strip() and b.strip() != "GO" for b in batches)


def test_without_a_server_no_database_is_made() -> None:
    for server, password in ((None, "pw"), ("127.0.0.1,1", None), ("", "")):
        with sql_server_schema("models", server, password) as url:
            assert url is None
