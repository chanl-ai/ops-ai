.PHONY: docs-verify

##@ Docs

docs-verify: ## Docs live in mapped docs/ folders; folder READMEs are briefs
	node scripts/check-docs.mjs
