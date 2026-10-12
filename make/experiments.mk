# Experiments in services/agents-service/experiments. They run on the scripted model with model keys unset. A script
# that reads a model key makes real model calls, which cost money and need the owner's approval per experiment, so it
# is refused unless APPROVED_REAL_CALLS names that experiment.
.PHONY: experiment

##@ Experiments

experiment: ## Run experiment E=<n> (e.g. E=1, E=2b) on the scripted model; ARGS= passes flags
	@test -n "$(E)" || { echo "usage: make experiment E=<n>   (one of: $$(ls $(SVC_DIR_agents)/experiments | sed -n 's/^e\([0-9a-z]*\)_.*\.py$$/\1/p' | tr '\n' ' '))"; exit 2; }
	@script=$$(ls $(SVC_DIR_agents)/experiments/e$(E)_*.py 2>/dev/null | head -1); \
	test -n "$$script" || { echo "no experiment e$(E)_*.py in $(SVC_DIR_agents)/experiments"; exit 2; }; \
	if grep -qE 'OPENAI_API_KEY|ANTHROPIC_API_KEY|--live-approved' "$$script"; then \
		if [ "$(APPROVED_REAL_CALLS)" != "$(E)" ]; then \
			echo "refused: $$script makes real model calls. Set APPROVED_REAL_CALLS=$(E) once the owner has approved them."; exit 3; fi; \
		echo "running $$script with real model calls (APPROVED_REAL_CALLS=$(E))"; \
		cd $(SVC_DIR_agents) && uv run python "$${script#$(SVC_DIR_agents)/}" $(ARGS); \
	else \
		echo "running $$script on the scripted model (model keys unset)"; \
		cd $(SVC_DIR_agents) && env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY uv run python "$${script#$(SVC_DIR_agents)/}" $(ARGS); \
	fi
