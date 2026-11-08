# Warm cloud boxes: a Fly Sprite that holds its own checkout and its own running stack, served at its own address.
# scripts/sprite-lane.sh does the work; scripts/box-setup.sh runs inside the box. Design: docs/architecture/cloud-boxes.md.
.PHONY: box-up box-url box-status box-sleep box-reset

##@ Cloud boxes (NAME=ops-ai-box-1)

box-up: ## Create the box if it is missing, else wake it, and set the stack up in it (BRANCH=main)
	@[ -n "$(NAME)" ] || { echo "make box-up: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh up $(NAME) $(BRANCH)

box-url: ## Print the box's console address, and require a Fly sign-in to open it
	@[ -n "$(NAME)" ] || { echo "make box-url: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh url $(NAME)

box-status: ## Awake or asleep, the branch, and the stack's health (does not wake a sleeping box)
	@[ -n "$(NAME)" ] || { echo "make box-status: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh status $(NAME)

box-sleep: ## Stop the app and side services, close the session, and confirm within 2 minutes that the box is not running
	@[ -n "$(NAME)" ] || { echo "make box-sleep: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh sleep $(NAME)

box-reset: ## Fresh main and the database back to the seeded state
	@[ -n "$(NAME)" ] || { echo "make box-reset: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh reset $(NAME)
