# The agent scripts (scripts/agents/): the repeatable part of a review, a test audit, a browser walk and the finder
# scorecard, run before an agent reads anything. Every path and command they use comes from .claude/project-profile.md.
.PHONY: agent-affected-usecases agent-review-context agent-test-audit agent-ui-walk agent-canary agent-canary-score agent-scripts-test

##@ Agent scripts

AGENT_OUT ?= .logs/agents

agent-review-context: ## One bundle for a reviewer: diff stat, files by layer with their docs, tests, new public surface, checks: make agent-review-context [BASE=origin/main]
	@python3 scripts/agents/review_context.py --base $(or $(BASE),origin/main) --out $(AGENT_OUT)/review-context.md

agent-test-audit: db-up ## Test effectiveness on the changed lines (mutation score, tests that cannot fail, failure modes with no test): make agent-test-audit [BASE=origin/main] [DESIGN=docs/design/<area>/<topic>.md] [PATHS="…"]
	@python3 scripts/agents/test_audit.py --base $(or $(BASE),origin/main) $(if $(DESIGN),--design $(DESIGN)) $(if $(PATHS),--paths $(PATHS)) --out $(AGENT_OUT)/test-audit.md

agent-ui-walk: ## Screenshots and findings per route, role and width on the running console: make agent-ui-walk ROUTES="/knowledge /tools" [AS=admin,member] [WIDTHS=1440,390] [STATES=1]
	@[ -n "$(ROUTES)" ] || { echo "make agent-ui-walk: name the routes, e.g. ROUTES='/knowledge /tools'" >&2; exit 2; }
	@node scripts/agents/ui_walk.mjs --routes $(ROUTES) $(if $(AS),--as $(AS)) $(if $(WIDTHS),--widths $(WIDTHS)) $(if $(STATES),--states) --out $(AGENT_OUT)/ui-walk

agent-affected-usecases: ## The use cases to run for a change, with layers, and the changed files none covers: make agent-affected-usecases [BASE=origin/main] [HEAD=HEAD]
	@python3 scripts/agents/affected_usecases.py $(or $(BASE),origin/main) $(or $(HEAD),HEAD)

agent-canary: ## Plant known bugs on a throwaway branch for a finder to look for; the answer key stays in $(AGENT_OUT)/canary-keys: make agent-canary [COUNT=6] [SEED=n]
	@python3 scripts/agents/seed_canaries.py plant --count $(or $(COUNT),6) $(if $(SEED),--seed $(SEED)) --key-dir $(AGENT_OUT)/canary-keys

agent-canary-score: ## Score a finder's report against a canary key: make agent-canary-score REPORT=findings.md KEY=$(AGENT_OUT)/canary-keys/<branch>.json
	@python3 scripts/agents/seed_canaries.py score --report $(REPORT) --key $(KEY)

agent-scripts-test: ## Every agent script's own red and green cases
	python3 scripts/agents/review_context.py --self-test
	python3 scripts/agents/seed_canaries.py --self-test
	node scripts/agents/ui_walk.mjs --self-test
	python3 scripts/agents/test_audit.py --self-test
	python3 scripts/agents/affected_usecases.py --self-test
