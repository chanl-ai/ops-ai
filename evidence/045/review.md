# c-045 independent review

One entry per commit, by a reviewer that did not build it. Checks ran on a clean `git archive` export of HEAD 3f2abc5
with its own database; the builder's working tree was never edited. Probes ran as throwaway scripts in that export
against the real `ops_identity` and `ops_service_kit` code. The walk step ran on the builder's worktree stack (console
:6016, tools-service :11720). Zero real model calls.

## 4530d87: the unused shared service token setting is gone

- Check: `scripts/verify-head.sh` at 3f2abc5 exits 0 (console, docs and every Python suite green).
- Read: the `service_token` field and its outside-dev check leave `Settings`; `model_config` keeps `extra="ignore"`, so a
  leftover `OPS_SERVICE_TOKEN` is dropped rather than refused.
- Grep beyond `src/` (the spec's grep covers only `src/`): `git grep` over the whole tree for `service_token`,
  `SERVICE_TOKEN` and `dev-service-token` finds only `mint_service_token`, `service_token_for`, test helpers that mint
  Ed25519 tokens (agents gateway conftest, platform-service conftest), and models-service's test that the old static
  token is refused (401). No script, Makefile target, compose file or console code reads or sends it.
- Docs: the identity page's shortcut row is gone. The operations rotation row names `OPS_SERVICE_SIGNING_KEY`,
  `OPS_SERVICE_SIGNING_KID` and `OPS_SERVICE_PUBLIC_KEYS`. Its order (new kid beside the old on every callee, restart
  callees, then the caller, then drop the old kid) matches `service_verifiers`, which maps each kid to one key and one
  service, so two kids for one service are trusted at once.
- Probe that held, production settings with `OPS_SERVICE_TOKEN=left-over` exported: during rotation both the old kid's
  and the new kid's tokens are accepted by tools-service's `ServiceAuth`; with the old kid dropped, its token is refused
  (Unauthorized) and the new one accepted. The static string as a bearer is refused. `Settings` has no `service_token`.
  With no signing key, production refuses to start ("service_signing_key must be set outside dev").
- Note, not blocking: the rotation row could say that dropping the old kid needs one more callee restart, and that the
  caller's new key needs its kid in `OPS_SERVICE_SIGNING_KID` (default `svc-dev`, which no production callee trusts).
- Verdict: accept.

## c1a9db4: build the production settings in a typed helper

- `tests/test_settings_without_shared_token.py`: with the field put back into `Settings` on the export, both tests fail
  (`assert not hasattr(production(), "service_token")`: `assert not True`); restored, both pass. `test_secrets.py` drops
  the argument that no longer exists. The e13 experiment mints agents-service's dev token for models-service; not run
  (it makes real model calls).
- Verdict: accept.

## 9c63e1e, 397db7b, 3f2abc5: live walk and verify results

- The walk ran on ec26f09 before the rebase; 397db7b records that. Verify passed 3/3 at 397db7b, and the later commits
  touch evidence only.
- The worktree stack runs with no `OPS_SERVICE_TOKEN` in its process environment or its `.env`.
- Verdict: accept.

## 81fff42: rotation names the new kid and restarts callees after the old kid goes

- Docs only. The operations rotation row now sets a new `OPS_SERVICE_SIGNING_KID` with the new key and restarts the
  callees again after dropping the old kid, matching `service_verifiers`, which reads `OPS_SERVICE_PUBLIC_KEYS` at
  start. This closes the note on 4530d87.
- Verdict: accept.

walk repeated: on the worktree stack, ran get_customer_profile through POST :11720/v1/calls as workflow:dispute_email with agents-service's Ed25519 token for tools-service -> 200, decision allow, ok true; the same call with the old static token as bearer -> 401 unauthorized; GET :11720/v1/tool-modules/mod_core_banking 200

verdict: approve
