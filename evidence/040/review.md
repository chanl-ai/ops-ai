# c-040 independent review

One entry per commit, by a reviewer that did not build it. Each check ran on a clean `git archive` export of the
commit against a private database; the working tree was never edited. Probes ran as extra tests in that export only,
through the real routes on platform-style tokens. Zero real model calls.

## e518d50: only Security's approvers decide a module's security review

- Defect, found by the builder's uc-040 and reproduced here: the role rule ran only when `auth_method != "dev"`, and
  platform-service's sign-in mints every person token with `auth_method: "dev"`. On the export of e518d50, an approver
  on team_platform holding a token shaped as platform-service mints it decided a review: 200, module published.
- Probes that held: an admin on team_platform is 403; an admin on team_security is 200; `X-Dev-User` with no bearer
  under platform auth is 401; the requester rule still refuses the requester.
- Verdict: changes requested; fixed in 74f78f2.

## 74f78f2: the Security rule holds for tokens from platform's dev sign-in

- Check: tools-service `make verify` on the export: lint and pyright clean, 92 passed, OpenAPI 35 operations, 3
  untyped on the allowlist. `make usecase-test UC=uc-040 LAYER=api`: 7 checks passed.
- Probe: the same platform-shaped approver token on team_platform is now 403 with the Security message (200 on
  e518d50, so the probe can fail). A signed-in person with no roles is 400 for want of a team and never reaches the
  rule.
- Not blocking: `verified = auth_method != "dev" or bool(roles)` infers the dev-header principal from its shape. Under
  platform auth that principal cannot exist (the header alone is 401), so `settings.auth_mode == "platform"` would
  state the same rule exactly. Worth doing if a principal with no roles ever gains a team.
- Verdict: accept.

## fb66c72: Security decides module reviews from Reviews and the module page (console)

- Check on the export of bc05668: console `pnpm verify` exit 0; `make usecase-test UC=uc-040 LAYER=ui`: 8 checks
  passed (requester's form off; a team_platform approver listed, form off, service 403; a reasonless Request changes
  sends nothing; Security approves from the Tool modules tab and the module publishes; the decided review leaves the
  tab; the module page shows it approved with no form; the publish dialog requires What changed; no page errors).
- Can fail: with the UI's Security gate replaced by `true`, the other-team check fails (`mOff: false`, the service
  still 403), so the form's state is tested, not only the service.
- Not blocking: with no `teamRoles` on the session the form is on (dev mode by design; the service still decides).
  The Reason field is labelled optional while Request changes requires it; the hint says so.
- Verdict: accept.

## bc05668: who decides a module's security review, and uc-040 (docs)

- Check: check-docs passes with the new page listed; the overview row matches 74f78f2's rule; usecases/040 run uc-040's
  api and ui layers, both green above.
- Verdict: accept.

## 1f668da: make up AUTH=platform signs people in through platform-service

- Check: on an export of HEAD 3992341, `make up ISOLATED=1 AUTH=platform` from nothing: all six rows healthy; the
  isolated stack's platform internal port is shifted with the rest (9711), so agents and tools verify against their own
  stack's platform-service.
- Defect: a stack already running in dev mode is not restarted. `make up ISOLATED=1`, then
  `make up ISOLATED=1 AUTH=platform`, printed "already running" for all four services, and a bare `X-Dev-User` then got
  200 from tools-service (`GET :9720/v1/tool-modules`). The target reports a platform stack while serving dev auth, so a
  walk run on it would pass the Security rule without exercising it. The pidfile check (`scripts/stack.sh:66`) needs
  the running auth mode recorded beside the pid and a restart, or a refusal, when it differs.
- Verdict: changes requested.

## 58ac569: the review form's Reason says when it is needed

- The field drops `optional`; the hint reads "Required to request changes; not needed to approve." uc-040 ui 8 checks
  on the export of HEAD.
- Verdict: accept.

## 9b9e6a4: live walk with three people on make up ISOLATED=1 AUTH=platform

- The steps, four screenshots and the :9720 calls match what I repeated below; the walk was on a fresh platform stack
  (the builder's bare `X-Dev-User` got 401), so the defect in 1f668da did not touch it.
- Verdict: accept.

## 4f1ab1e: Reviews counters say they cover runs and publishes, and how many module reviews wait

- The Open reviews card names its scope and shows tools-service's `security_review` count beside it; both counts come
  from their services, nothing is joined in the page. uc-040 ui 8 checks on the export of HEAD.
- Verdict: accept.

## 51cbd9d: make up restarts a service started under the other auth mode

- Re-ran the 1f668da repro on an export of 51cbd9d. `make up ISOLATED=1`: a bare `X-Dev-User` got 200. Then
  `make up ISOLATED=1 AUTH=platform`: all four services printed "running with auth dev, asked for platform;
  restarting", the health table showed "auth platform", and the bare header got 401. The same command again printed
  "already running ... auth platform" and stayed 401. Back to dev restarted all four and got 200.
- Verdict: accept; 1f668da's defect is fixed.

## Card

walk repeated: on `make up ISOLATED=1 AUTH=platform` (export of HEAD), James, Maya and Nadia signed in through
platform-service (POST :9710/v1/auth/sign-in 200 each); James created mod_3a064cd36fa4 and requested a review
(POST :9720/.../reviews 200) -> James deciding got 403 "You requested this review", Maya (approver, team_ops) 403
"Only an approver or admin on the Security team", a bare X-Dev-User 401; Nadia's security_review view listed it (count
1) and her approval returned 200, published 0.1.0 (POST :9720/v1/tool-modules/mod_3a064cd36fa4/reviews/rev_5f152144c567/decide).

verdict: approve
