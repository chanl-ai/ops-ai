# Eval runner

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Runs workflow suites on publish requests, agent evals, model-update runs and gate self-tests; scores against baselines; applies injection thresholds; seals evidence bundles. |
| Owns | PostgreSQL (runs, results, baselines); evidence bundles in the WORM object store. |
| Depends on | The interpreter (runs on the production path in `test`), the AI gateway, the control plane, `services/shared`. |
| Specs | `docs/specs/04-evals-and-release.md` 4.1–4.6, 5.1–5.4, 5.8–5.10 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
