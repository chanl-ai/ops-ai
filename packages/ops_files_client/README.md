# ops_files_client

The client other services use to put file bytes in files-service and to read, attach and detach them by file id,
over HTTP with a service token naming the tenant. It does not import `ops_files`: files-service's code belongs to
files-service alone. Routes: `services/files-service/openapi.json` (`/v1/files`, with a service token naming the team); docs:
`docs/services/files-service/overview.md`.

```python
from ops_files_client import FilesClient

files = FilesClient.from_settings(Settings(), service="agents")
stored = await files.write(
    "local",
    "team_ops",
    data,
    name="statement.pdf",
    mime="application/pdf",
    purpose="chat_attachment",
    uploaded_by="james@harborpine.example",
)
body = await files.read("local", "team_ops", stored.file.id)
```
