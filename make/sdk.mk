# The Python and TypeScript SDKs in sdk/ (docs/sdk/): the generated layer, its drift check and the SDKs' tests.

# The sdk/ folder exists, so without .PHONY `make sdk` reports it up to date and generates nothing.
.PHONY: openapi sdk sdk-verify sdk-check sdk-typed-proof
openapi: ## After a route or DTO change: regenerate every service's openapi.json, then the SDKs, in one step
	@for svc in services/*/; do if [ -f "$$svc/scripts/check_openapi.py" ]; then (cd "$$svc" && uv run --quiet python scripts/check_openapi.py --write) || exit 1; fi; done
	$(MAKE) -s sdk

sdk: ## Regenerate the SDKs' generated layer after a route changes (sdk/generate.py)
	uv run python sdk/generate.py

sdk-verify: ## The generated layer matches the services' documents, and both SDKs' tests pass (no stack needed)
	@# SDK_REF=HEAD reads the documents as committed, for a tree other sessions share.
	uv run python sdk/generate.py --check $(if $(SDK_REF),--ref $(SDK_REF))
	uv run --isolated --quiet --with pytest --with-editable sdk/python pytest -q sdk/python/tests
	pnpm --silent --filter @chanl-ai/ops-ai test

sdk-check: ## sdk-verify, the packages installed in an empty folder, and the examples on `make up` (SDK_LIVE=0 skips them)
	bash sdk/check.sh

# AS defaults to builder for this target. After `dev.mk` sets AS := admin, $(or $(AS),builder)
# would always pick admin; only a command-line or environment AS= overrides the builder default.
sdk-typed-proof: ## Typed SDK returns against a live env: make sdk-typed-proof AS=builder [ENV=local|staging] [TEAM=]
	@uv run --quiet python scripts/sdk_typed_proof.py \
		--as '$(if $(filter command line environment,$(origin AS)),$(AS),builder)' \
		--env $(or $(ENV),local) $(if $(TEAM),--team $(TEAM))
