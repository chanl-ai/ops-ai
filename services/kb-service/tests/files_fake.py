"""files-service faked for kb's tests; the fake lives with the client, where every service's tests share it."""

from ops_files_client.testing import FakeFilesService

__all__ = ["FakeFilesService"]
