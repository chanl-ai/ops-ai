# A banker finds, starts and continues chats

Status: current. Id: `uc-087`. Service: `console`. Layers: ui.

James chats with an agent the way he uses ChatGPT: he starts a chat from the chat home, regenerates an answer, stops a
slow reply, retries a refused send, scrolls his chats column and finds an old chat by what he asked. The list's search and
paging run on the server (`GET /chat/threads` with `search` and `cursor`). Design: [chat](../../console/chat.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | the runner picks free ports and a database of its own |

The script starts platform-service and the agents service on the scripted model; no model key is needed. A slow or
refused reply is made in the browser by holding or refusing the request, so neither the console nor a service has a
test-only branch.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Chat with no chats and opens the folded chats column (Show chats) | The column says "No chats yet. Ask something to start one." |
| 2 | He types a first message on the chat home and sends it | A thread starts with that message and is answered |
| 3 | Regenerate | The answer is replaced: still one answer, with a new id |
| 4 | Send while the request is held | Stop and "Thinking…" show; Stop hands the composer back and nothing is stored |
| 5 | Send while the server refuses with 503 | "Your message wasn't sent" with the reason; Retry sends it |
| 6 | 33 more chats; search "saskatchewan" | Only the oldest chat, past the first page, is found by its question; its title does not hold the word |
| 7 | Clear the search, scroll to the end of the column | 30 chats, then the next page as the end comes into view, all of them, none twice |
| 8 | The list request fails | "Couldn't load chats. Try again" on a button; pressing it loads the list |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-087-ui.mjs` | passing |

## Non-vacuous check

Step 6: the matching chat is the oldest, so it is not among the 30 rows loaded when the search runs, and its title
stops before the word. A column that filtered its loaded rows in the browser finds nothing; an API that searched titles
only finds nothing. Removing the question clause from `matching_ids` (chat_threads.py) fails the same case in
`tests/api/test_chat_list_and_overrides.py`.
