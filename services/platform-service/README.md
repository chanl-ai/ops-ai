# Platform service

Status: first slice built. `make up` starts it on :8710 (internal :8711); `make -C services/platform-service verify`.

The identity issuer. It owns tenants, teams, users, members, sessions, invites, API keys and the audit log, and it is
the only service that mints tokens. Tokens are signed with Ed25519 and the public keys are published as JWKS, so every
other service verifies callers locally. It is not a gateway: requests go to each service directly.

Overview, design and operations: `docs/services/platform-service/overview.md`.
