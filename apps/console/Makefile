# The console: Next.js on :3016 (ISOLATED=1: :4016), chat on the agents service. Same verbs as every service Makefile.
STACK_SVC := console
include ../../make/service-common.mk
.PHONY: install run test lint typecheck verify migrate clean

##@ Console

install: ## pnpm install at the workspace root
	cd ../.. && pnpm install

run: ## next dev in the foreground on :3016 (ISOLATED=1: :4016), chat on the agents service
	NEXT_PUBLIC_OPS_CHAT_API_URL=http://localhost:$(OPS_AGENTS_PORT) pnpm exec next dev -p $(OPS_CONSOLE_PORT)

test: ## No console tests yet; typecheck and the standards check are the gate
	@echo "console: no tests yet (verify runs tsc and the standards check)"

lint: ## Console standards check
	pnpm check:standards

typecheck: ## tsc --noEmit
	pnpm typecheck

verify: ## tsc and the standards check
	pnpm verify

migrate: ## Nothing to migrate
	@echo "console: no migrations"

clean: ## Remove the Next build directories
	rm -rf .next .next-isolated tsconfig.tsbuildinfo
