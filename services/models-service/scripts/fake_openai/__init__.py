"""A stand-in OpenAI chat API for running models-service, and the agents behind it, with no model key and no network.

Run it with `python -m fake_openai <dir>` (see __main__.py). A provider connection of type openai-compatible whose base
URL is this server's `/v1` sends every alias bound to it here; changing that base URL back to api.openai.com is the
only change that makes the same aliases real (docs/services/models-service/overview.md)."""
