.PHONY: docs-verify

##@ Docs

docs-verify: ## Docs live in mapped docs/ folders; folder READMEs are briefs
	node scripts/check-docs.mjs
	node scripts/check-public-paths.mjs --self-test
	node scripts/check-public-paths.mjs
	python3 scripts/agent_skills.py --check
