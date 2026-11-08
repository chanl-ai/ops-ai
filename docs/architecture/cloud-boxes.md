# Cloud boxes

A box is a Fly Sprite that holds its own checkout of the repository and runs the whole stack, so feature work and its preview never touch the shared staging app. A box has no Docker: PostgreSQL, OPA, Mailpit and GreenMail run as programs the box keeps running (`sprite-env services`), and the console and its services run as `make up` starts them on a laptop.

Status: pilot, one box (`ops-ai-box-1`).

## Commands

| Command | What it does |
|---|---|
| `make box-up NAME=ops-ai-box-1 [BRANCH=]` | Creates the box if it is missing, else wakes it, then runs `scripts/box-setup.sh` inside it. |
| `make box-url NAME=` | Prints the one-time link, `<address>/__box?key=<key>`. Opening it sets the `ops_box` cookie (HttpOnly, Secure, SameSite=Lax) and lands on the login page. Every request without the cookie gets 403. The demo sign-in stays, since the gate keeps strangers out. |
| `make box-status NAME=` | Awake (`running`, `warm`) or asleep (`cold`), the branch, and `make health`. A cold box is not woken to be asked. |
| `make box-check NAME=` | Headless, from the laptop, through the public address: no cookie gets 403, the link sets the cookie and lands on login, a demo sign-in stays on chat for 10 seconds, and `GET /api/platform/v1/teams` with the app's token answers 200. |
| `make box-sleep NAME=` | Closes sessions, leaves the stack running, and waits until the status is `cold`. Fly suspends an idle box with its processes intact, so the next wake is instant. |
| `make box-stop NAME=` | As `box-sleep`, after stopping the stack and the box's services. |
| `make box-reset NAME= [BRANCH=]` | Fresh main (or the branch) and the database back to the seeded state. |

## How it is wired

- The address is public because Fly's organization-only setting replaces the app's `Authorization` header on every call, which sent the console into a login loop. A gate Caddy (`~/box/Caddyfile`, written by `scripts/box-setup.sh`, port 8081, set with `--http-port`) admits only requests with the `ops_box` cookie. The key is made once at `box-up`, kept in `~/box/key` (mode 600) and printed only by `make box-url`. The gate forwards to Caddy (`deploy/fly/Caddyfile`, port 8082), which routes `/api/<service>/` to each service and everything else to the console. GreenMail holds the box's default port 8080.
- The console is started with `OPS_PUBLIC_ORIGIN`, so its calls go to `<address>/api/<service>` (`scripts/stack.sh`, `apps/console/next.config.ts`).
- `OPS_DATABASE_URL`, when given to `box-setup.sh`, replaces the box's own PostgreSQL; nothing else changes.
- The box runs on the fake model and holds no provider keys.

## Not done

- The builder does not run inside the box yet. It needs a Claude sign-in token and a GitHub token limited to this repository, which the owner provides.
- Memory use of the running stack is about 11 GB of the box's 16 GB; no screen-test run has been timed in a box.
