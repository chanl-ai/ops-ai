# Purge derived data after a file deletion

When files-service reports `file.deleted`, the shipped system workflow `file_deleted_purge` removes derived extractions. This folder is the copyable YAML, not a second listener. A team copy is never started by the event. The product badges it **system / event-started**.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/11-purge-after-file-deleted/setup.py
uv run pytest examples/workflows/11-purge-after-file-deleted/test_example.py
```

After setup:

```bash
cd examples/workflows/11-purge-after-file-deleted
OPS_CONFIG=.ops-profile.json ops workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows apply resources/workflow.yaml
```

Start it by deleting a team file. There is no send-test-event command; `POST /v1/events` is a service token route.

```python
file_id = ops.upload("note.txt", b"purge-me\n", mime="text/plain", purpose="case_attachment")["id"]
ops.raw.files.files_delete_file(file_id)
# file_deleted_purge runs and ends purged
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | delete an uploaded file | system run `purged` |
| Alternate | the same deleted file again | `purged` again, nothing more removed |
| Failure | a file that still exists | this copy ends `purge_failed` |

Nodes: `ops.trigger.event` (`file.deleted`) → `ops.documents.purge` → `ops.flow.end` (`purged` / `purge_failed`). Open the printed `/workflows/definitions/<id>`.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
