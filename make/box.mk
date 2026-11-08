# Warm cloud boxes: a Fly Sprite that holds its own checkout and its own running stack, served at its own address.
# scripts/sprite-lane.sh does the work; scripts/box-setup.sh runs inside the box. Design: docs/architecture/cloud-boxes.md.
.PHONY: box-up box-url box-status box-check box-sleep box-stop box-reset

##@ Cloud boxes (NAME=ops-ai-box-1)

box-up: ## Create the box if it is missing, else wake it, and set the stack up in it (BRANCH=main)
	@[ -n "$(NAME)" ] || { echo "make box-up: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh up $(NAME) $(BRANCH)

box-url: ## Print the one-time link that opens the box in a browser
	@[ -n "$(NAME)" ] || { echo "make box-url: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh url $(NAME)

box-status: ## Awake (running or warm) or asleep (cold), the branch, and the stack's health; does not wake a sleeping box
	@[ -n "$(NAME)" ] || { echo "make box-status: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh status $(NAME)

box-check: ## Headless through the public address: gate, link, sign-in, chat, API
	@[ -n "$(NAME)" ] || { echo "make box-check: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh check $(NAME)

box-sleep: ## Close sessions and wait until the box is cold (a few minutes); the stack keeps running inside it for an instant wake
	@[ -n "$(NAME)" ] || { echo "make box-sleep: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh sleep $(NAME)

box-stop: ## Stop the app and the side services as well, then wait until the box is cold
	@[ -n "$(NAME)" ] || { echo "make box-stop: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh stop $(NAME)

box-reset: ## Fresh main (or BRANCH=) and the database back to the seeded state
	@[ -n "$(NAME)" ] || { echo "make box-reset: name the box, e.g. NAME=ops-ai-box-1"; exit 2; }
	@bash $(ROOT)/scripts/sprite-lane.sh reset $(NAME) $(BRANCH)
