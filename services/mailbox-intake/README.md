# Mailbox intake

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Polls shared mailboxes with Microsoft Graph delta queries every 60 s per folder, scans and archives each mail and attachment, emits the new-mail event that starts a run, and reconciles daily so every mail has an intake record. |
| Owns | PostgreSQL (mailbox state, intake records); mail archive in the WORM object store. |
| Depends on | Microsoft Graph, the control plane, the object store, `services/shared`. |
| Specs | `docs/specs/03-data-and-ai-gateways.md` 4.6, 5.6; ADR-0007 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
