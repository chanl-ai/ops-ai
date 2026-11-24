# Staging on one Fly app from one image (docs/deploy/fly-staging.md): build, deploy, migrate, grants, health, click walk, smoke check.
# App names come from ~/.config/ops-ai/staging.env (deploy/fly/staging.env.example); each recipe loads it with stg_env.sh
# and stops with a message when it is missing.
.PHONY: stg-deploy stg-deploy-ci stg-health stg-rollback stg-smoke

##@ Staging

stg-deploy: ## Build and deploy REF (default HEAD) to your staging app (STG_APP), apply grants, check every process, walk the console
	sh $(ROOT)/deploy/fly/stg_deploy.sh

stg-deploy-ci: ## Deploy REF (default develop) to staging on GitHub (deploy-staging.yml) and watch the run; SKIP_WALK=1, REASON=; changes the live app
	sh $(ROOT)/deploy/fly/stg_deploy_ci.sh

stg-rollback: ## Swap the machine back to the image of the release before the current one (or TO=<sha>) and check every process: no build, grants or walk
	@. $(ROOT)/deploy/fly/stg_env.sh; ref="$(TO)"; [ -n "$$ref" ] || ref=$$(fly releases -a "$$STG_APP" --json | python3 -c \
	  "import json,sys; r=[x for x in json.load(sys.stdin) if x['Status']=='complete']; print(r[1]['ImageRef'].rsplit(':',1)[1] if len(r)>1 else '')"); \
	[ -n "$$ref" ] || { echo "stg-rollback: no earlier release"; exit 1; }; \
	echo "stg-rollback: to $$ref (migrations stay applied; they only add)"; \
	REF=$$ref STG_ROLLBACK=1 sh $(ROOT)/deploy/fly/stg_deploy.sh

stg-smoke: ## Run the deploy's smoke check (deploy/fly/smoke.mjs) against staging without deploying, as the roles team's admin in STG_ROLES_TEAM; writes to staging, so only the owner runs it
	sh $(ROOT)/deploy/fly/stg_smoke.sh

stg-health: ## Every process on the staging machine, up or down
	@. $(ROOT)/deploy/fly/stg_env.sh; fly ssh console -a "$$STG_APP" -C "python3 /app/deploy/host/ops_host.py --check /app/deploy/fly/processes.toml"
