# Included by the Makefile of a planned service (docs/architecture/service-map.md) so `make -C services/<x> help`
# answers everywhere. Every verb says the service is not started; OWN_VERBS lists verbs the including Makefile
# defines itself (a library with tests but no server yet).
include $(dir $(lastword $(MAKEFILE_LIST)))env.mk
.DEFAULT_GOAL := help
SERVICE_VERBS := install run stop test lint typecheck verify migrate logs health clean
.PHONY: help $(SERVICE_VERBS)

help: ## List this Makefile's targets
	@echo "$(SERVICE_NAME): $(SERVICE_STATUS)"
	@awk "$$HELP_AWK" $(firstword $(MAKEFILE_LIST))
	@printf '  %-20s %s\n' $(foreach v,$(filter-out $(OWN_VERBS),$(SERVICE_VERBS)),$(v) "not started")

$(filter-out $(OWN_VERBS),$(SERVICE_VERBS)):
	@echo "$(SERVICE_NAME) $@: not started ($(SERVICE_STATUS))"
