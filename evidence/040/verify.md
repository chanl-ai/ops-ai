<!-- codeloop verify: start -->
# Verify c-040

result: pass
sha: 399234193da5758317795a9660ea701ee5206647
env: local

| Use case | Accepts | Layers |
|---|---|---|
| us1-reviews-tab | US1 | cli pass |
| us2-security-decides | US2 | cli pass |
| us3-module-page-state | US3 | cli pass |
| us4-publish-hint | US4 | cli pass |
<!-- codeloop verify: end -->

## Live walk

stack: make up ISOLATED=1 AUTH=platform (console :4016 signing in through platform-service :9710; agents :9700 and tools :9720 verifying platform tokens; 1f668da)
url: http://localhost:4016/reviews

steps:
- Setup through tools-service's API as James Richardson: listed the statements host and created module mod_41a793e19b61 with one read operation.
- James (builder, Operations) signed in and pressed Request security review on the module page: the review is pending, and his Approval tab shows the decision form switched off, reading "Security decides" and "You requested this review. Someone in Security decides it." Screenshot: live-1-requester-cannot-decide.png
- Maya Okafor (approver, Operations) signed in: Reviews > Tool modules lists the module, and its decision form is off with "Only an approver or admin on the Security team decides module reviews." Screenshot: live-2-other-team-approver-blocked.png
- Maya's decision sent straight to tools-service: 403 "Only an approver or admin on the Security team decides a module's security review."
- Nadia Petrov (approver, Security) signed in, opened the module from Reviews > Tool modules and pressed Approve and publish: the row left the tab. Screenshot: live-3-security-decides.png
- Back on the module page: the review is approved by Nadia Petrov, and tools-service reports the module published at v0.1.0. Screenshot: live-4-published.png
- The demo login is not prefilled under platform sign-in; it exists only on the mock provider.

network:
- GET http://localhost:9720/v1/tool-modules/mod_41a793e19b61 200
- POST http://localhost:9720/v1/tool-modules/mod_41a793e19b61/reviews 200
- GET http://localhost:9720/v1/tool-modules/mod_41a793e19b61 200
- GET http://localhost:9720/v1/tool-modules/mod_41a793e19b61 200
- GET http://localhost:9720/v1/tool-modules?page=1&pageSize=1&view=security_review 200
- GET http://localhost:9720/v1/tool-modules?page=1&pageSize=100&view=security_review 200
- GET http://localhost:9720/v1/tool-modules?page=1&pageSize=1&view=security_review 200
- GET http://localhost:9720/v1/tool-modules?page=1&pageSize=100&view=security_review 200
- POST http://localhost:9720/v1/tool-modules/mod_41a793e19b61/reviews/rev_4809797db20f/decide 200
- GET http://localhost:9720/v1/tool-modules?page=1&pageSize=1&view=security_review 200
- GET http://localhost:9720/v1/tool-modules?page=1&pageSize=100&view=security_review 200
- GET http://localhost:9720/v1/tool-modules/mod_41a793e19b61 200

external: none: deciding a security review changes the module's state in tools-service and calls no outside system.
