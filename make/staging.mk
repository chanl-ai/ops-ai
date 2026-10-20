# Staging on one Fly app from one image (docs/deploy/fly-staging.md): build, deploy, migrate, grants, health, click walk.
.PHONY: stg-deploy stg-health

##@ Staging

stg-deploy: ## Build and deploy REF (default HEAD) to <your-app>-one, apply grants, check every process, walk the console
	sh $(ROOT)/deploy/fly/stg_deploy.sh

stg-health: ## Every process on the staging machine, up or down
	fly ssh console -a $(or $(STG_APP),<your-app>-one) -C "python3 /app/deploy/host/ops_host.py --check /app/deploy/fly/processes.toml"
