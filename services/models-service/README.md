# Models service

The console calls this the AI gateway.

Status: first slice built: aliases, keys and budgets, admission, a metadata-only call log, and OpenAI-compatible
completions through the scripted provider or any openai-compatible connection. On :8730 (`make run`).

Every model call leaves through this service. Agent workers hold a model key, never a provider credential.

Whether an alias reaches a real or a fake model is decided by its provider connection's base URL, not by code.
`scripts/fake_openai` is a keyless stand-in for OpenAI's chat API; `OPS_MODELS_FAKE_OPENAI_URL` seeds connection
`openai-local` at it with alias `default`, and `PUT /v1/models/providers/openai-local` moves it to
`https://api.openai.com/v1` and back. Steps: `docs/services/models-service/overview.md`, "Real or fake model, by
connection".

Design: `docs/architecture/service-map.md` and `docs/services/models-service/overview.md`.
