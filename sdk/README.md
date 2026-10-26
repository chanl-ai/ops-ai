# SDKs

The Python (`python/`, `ops-ai`) and TypeScript (`typescript/`, `@chanl-ai/ops-ai`) SDKs for the platform's public API.
Guides: [Python](../docs/sdk/python.md), [TypeScript](../docs/sdk/typescript.md).

| Command | What it does |
|---|---|
| `make sdk` | Regenerates both SDKs' generated layer from the services' OpenAPI documents (`generate.py`) |
| `make sdk-verify` | The generated layer matches the documents, and both SDKs' tests pass; part of `make verify` |
| `make sdk-check` | `sdk-verify`, the packages installed in an empty folder, and the examples on `make up` |

Only operations marked `x-ops-public: sdk` or `both` are generated (`docs/architecture/api.md`). Publishing is
`.github/workflows/sdk-publish.yml`: a dry run until the owner turns it on.
