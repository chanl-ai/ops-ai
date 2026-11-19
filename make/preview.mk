# Preview stacks: a branch in review gets its own worktree and its own running stack on its own ports, at most three,
# while :3016 runs the latest main. scripts/preview.py owns the list and the offsets; the stack is the ordinary one.
#   make wt BRANCH=feat/x          worktree under ../ops-ai-worktrees/feat/x, installs, starts its stack
#   make wt-list                   branch, console URL and age; regenerates the local page
#   make wt-stop BRANCH=feat/x     stops it by pid; its data and worktree stay
#   make review-main               moves :3016 to the latest origin/main and restarts it (data stays)
.PHONY: wt wt-list wt-stop review-main

##@ Preview stacks

PREVIEW_WORKTREES ?= $(abspath $(STACK_HOME)/../ops-ai-worktrees)
PREVIEW_PAGE ?= $(STACK_HOME)/.run/previews.html
PREVIEW = python3 $(ROOT)/scripts/preview.py --home $(STACK_HOME) --worktrees $(PREVIEW_WORKTREES) --run-root $(STACK_HOME)/.run --page $(PREVIEW_PAGE) $(if $(DRY_RUN),--dry-run)

wt: ## Worktree and stack for BRANCH on the next free port offset (shared package caches); refuses a fourth, naming the three
	@$(PREVIEW) start --branch "$(BRANCH)"

wt-list: ## Each preview's branch, console URL and age; rewrites the previews page (PREVIEW_PAGE, default .run/previews.html)
	@$(PREVIEW) list

wt-stop: ## Stop BRANCH's preview by pid; its data stays
	@$(PREVIEW) stop --branch "$(BRANCH)"

review-main: ## Move the :3016 stack to the latest origin/main and restart it, never reset (DRY_RUN=1 prints the steps)
	@[ -e "$(REVIEW_DIR)/.git" ] || { echo "make review-main: no review worktree at $(REVIEW_DIR); make review BRANCH=main makes it"; exit 1; }
	@[ -z "$$(git -C "$(REVIEW_DIR)" status --porcelain --untracked-files=no)" ] || { echo "make review-main: $(REVIEW_DIR) has uncommitted changes; commit or remove them there"; exit 1; }
	@if [ -n "$(DRY_RUN)" ]; then echo "would: git fetch origin main; checkout --detach origin/main in $(REVIEW_DIR); AUTH=platform OPS_CONSOLE_PORT=3016 make -C $(REVIEW_DIR) restart"; exit 0; fi; \
	  git -C "$(STACK_HOME)" fetch -q origin main && \
	  git -C "$(REVIEW_DIR)" checkout -q --detach origin/main && \
	  $(MAKE) -s -C "$(REVIEW_DIR)" install && \
	  AUTH=platform OPS_CONSOLE_PORT=3016 $(MAKE) -C "$(REVIEW_DIR)" restart
