# The console. `dev` and `dev-runtime` run it in the foreground; `make up` runs it in the background with the rest.
.PHONY: console-install dev dev-runtime console-verify

##@ Console

console-install: ## pnpm install (also installs the pre-commit hook)
	pnpm install

dev: ## Console on the mock API, http://localhost:3016 (foreground)
	pnpm dev

dev-runtime: ## Console with chat on the agents service (:8700), http://localhost:3017 (foreground)
	pnpm dev:runtime

console-verify: ## Type-check the console and run its standards check
	pnpm --filter @ops-ai/console verify
