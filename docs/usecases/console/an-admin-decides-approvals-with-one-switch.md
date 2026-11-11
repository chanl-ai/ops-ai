# An admin decides whether agents ask before changing an app with one switch

Status: current. Id: `uc-730`. Service: `console`. Layers: ui.

Agents change apps without asking until a team admin turns on one switch on Settings > Approvals, "Ask before an agent
changes anything in an app". Once on, the admin picks who answers: the person in the chat, or a reviewer of a chosen
role. "People can approve their own requests" is shown only while a reviewer answers. Under Advanced, "Test accounts
never ask" is on until the team saves it off. The old approval rows and "Requester may decide" are no longer on Policies.
Settings, defaults and who changes them: `docs/architecture/roles-and-permissions.md`, section Approvals.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A first-time admin sees one switch, off, and is asked who answers only once it is on | ui | 1-2 | 2 |
| S2 | Self-approval is offered only while a reviewer answers, and starts off | ui | 2 | 2 |
| S3 | Test accounts never ask is on until a team saves it off, and the saved choice survives a reload | ui | 3 | 3 |
| S4 | Policies holds none of the approval rows and no Requester may decide, and loads without a refused request | ui | 4 | 4 |
| S5 | A saved self-approval choice is kept | ui | 5 | 5 |
| S6 | A member who cannot change a setting reads "Only an admin can change this", with the right article | ui | 6 | 6 |
| S7 | A Real test run of a write on a live account shows the approval card; Deny sends nothing, Allow runs it | ui | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The run's demo stack | the runner starts the console, platform sign-in and the services (`packages/usecase-runner/src/harness.ts`) |

Wanjiru Kamau is an admin of every team; her own team has saved no approval setting.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru opens Settings > Approvals | One switch, off; no question about who answers; no self-approval checkbox |
| 2 | She turns it on, then picks Ask a reviewer | Ask the person is chosen first and shows no self-approval checkbox; after she picks a reviewer, "People can approve their own requests" appears, off |
| 3 | She opens Advanced, unchecks "Test accounts never ask", saves and reloads | It was on before; it stays off after the reload; she checks it again and saves |
| 4 | She opens Settings > Policies | None of the approval rows, and no "Requester may decide"; no request the page makes is refused or missing |
| 5 | She turns the switch on, picks Ask a reviewer and a role, ticks self-approval, saves and reloads | It is still ticked |
| 6 | Ravi, a viewer, opens Settings > Approvals | The lock reads "Only an admin can change this" |
| 7 | James runs (the script does this before step 5, which lets approvers approve their own requests) a write on a live account from a tool's Test panel (Real), then answers the card | The run is held and nothing is sent; the card offers Allow and Deny and no "Allow for this chat"; Deny sends no second run; running again and choosing Allow sends the write to the app (the gateway allowed it and reached the bank) |

## Acceptance layers

| Layer | Script | Proves |
|---|---|---|
| ui | `scripts/test-uc-730-ui.mjs` | Steps 1 to 7 in a real browser |

## Non-vacuous check

Step 2's self-approval check and step 3's reload check fail when the checkbox is missing from Approvals (seen before the
checkbox was added: the checkbox was not found).
