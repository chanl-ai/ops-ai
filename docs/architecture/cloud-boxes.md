# Cloud boxes

A box is a Fly Sprite that holds its own checkout of the repository and runs the whole stack, so feature work and its preview never touch the shared staging app. A box has no Docker: PostgreSQL, OPA, Mailpit and GreenMail run as programs the box keeps running (`sprite-env services`), and the console and its services run as `make up` starts them on a laptop.

Status: pilot, one box (`ops-ai-box-1`).

## Commands

| Command | What it does |
|---|---|
| `make box-up NAME=ops-ai-box-1 [BRANCH=]` | Creates the box if it is missing, else wakes it, then runs `scripts/box-setup.sh` inside it. |
| `make box-url NAME=` | Prints the console address and sets the address to require a Fly sign-in. People then sign in through the app's own login. |
| `make box-status NAME=` | Awake (`running`, `warm`) or asleep (`cold`), the branch, and `make health`. A cold box is not woken to be asked. |
| `make box-check NAME=` | Headless, from the laptop: the address refuses a visitor without a Fly sign-in, the login page loads, a demo sign-in lands on chat. |
| `make box-sleep NAME=` | Closes sessions, leaves the stack running, and waits until the status is `cold`. Fly suspends an idle box with its processes intact, so the next wake is instant. |
| `make box-stop NAME=` | As `box-sleep`, after stopping the stack and the box's services. |
| `make box-reset NAME= [BRANCH=]` | Fresh main (or the branch) and the database back to the seeded state. |

## How it is wired

- One public address reaches Caddy (`deploy/fly/Caddyfile`, port 8081, set with `--http-port`), which routes `/api/<service>/` to each service and everything else to the console. GreenMail holds the box's default port 8080.
- The console is started with `OPS_PUBLIC_ORIGIN`, so its calls go to `<address>/api/<service>` (`scripts/stack.sh`, `apps/console/next.config.ts`).
- `OPS_DATABASE_URL`, when given to `box-setup.sh`, replaces the box's own PostgreSQL; nothing else changes.
- The box runs on the fake model and holds no provider keys.

## Not done

- The builder does not run inside the box yet. It needs a Claude sign-in token and a GitHub token limited to this repository, which the owner provides.
- Memory use of the running stack is about 11 GB of the box's 16 GB; no screen-test run has been timed in a box.
