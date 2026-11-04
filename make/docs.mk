.PHONY: docs-verify

##@ Docs

docs-verify: ## Docs live in mapped docs/ folders; folder READMEs are briefs
	node scripts/check-docs.mjs
	node scripts/check-public-paths.mjs --self-test
	node scripts/check-public-paths.mjs
	python3 scripts/scrub_board_paths.py
	python3 scripts/agent_skills.py --check
	python3 scripts/wf_builder_examples.py --check
	@# It reads the examples' YAML, so it runs on the workspace's Python, which has PyYAML; a bare runner's python3 does not.
	uv run --quiet python scripts/check_examples.py --check
