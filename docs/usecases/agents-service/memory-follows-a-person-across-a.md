# Memory follows a person across a team's agents and they take it back

Status: current. Id: `uc-561`. Service: `agents-service`. Layers: api.

What a person tells one agent in a team, every agent in that team knows, and nothing of it reaches another team. A
change replaces the old value and keeps it as history; a contradiction of something the person confirmed is asked
about instead of replacing it. The person can undo what a reply remembered, take back a forget for 30 days, and erase
a memory for good.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The scripted model | The harness's agents service, which reads "I prefer ..." and "my <thing> is ..." as memories |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The person, acting in one team, tells the Branch agent they prefer short bullet points | The reply says it remembered it: in use, new |
| 2 | They say it again to the Dispute agent | Confirmed, not saved twice; My memory lists it once |
| 3 | The Dispute agent searches its memory for it | Found |
| 4 | The same person, acting in another team, searches and lists their memory | Nothing found, nothing listed |
| 5 | They give a timezone, then a new one | The new value replaces the old; only the new one is listed |
| 6 | They confirm the timezone, then change it ("Actually my timezone is Mountain") | The new value replaces the confirmed one; only it is listed |
| 7 | They undo the remembered preference | Not listed, not found; the first reply shows it forgotten, with no text |
| 8 | They forget the timezone, then undo the forget | Listed again |
| 9 | They erase it, then try to undo | Erased; the undo answers not found |
| 10 | They say "Remember that I prefer plain answers without tables." | One memory, new |
| 11 | They say it again to the Dispute agent | The same memory, confirmed; My memory lists it once, as asked for, not as corrected |
| 12 | They say "Remember that I prefer answers with a short table.", and the model calls it the same memory | It replaces the old preference; only the new one is listed |
| 13 | They say "Remember that I prefer short numbered summaries." | Kept |
| 14 | They say "Actually, change that: I prefer short bullet-point summaries, not numbered ones." | It replaces the numbered one, in use, with no question left waiting; only the new one is listed |
| 15 | They ask for a summary of their day | The summary comes in bullet points |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-561-api.py` | passing |

## Non-vacuous check

Step 4's list check failed on its first run (2026-10-29): acting in the other team, My memory still listed the
preference, because the list relied on the team filter that passes every team for a dev caller. The list now names the
team the request acts in, and the step passes. Each forget, undo and erase check is paired with a list or search that
shows the memory before it, so a memory that was never saved cannot pass as removed.

Steps 10 and 11 failed on their first run (2026-10-29), with the scripted model quoting the whole "remember that"
message as a real model does: the reply saved two memories, the second a copy marked as written by the person, and
saying it again replaced that copy with itself. Asked saves now accept a quote that holds the asking words.

Step 12 failed on its first run (2026-10-29), with the scripted model answering "same" for any saved preference as a
real model did: the reply said "same" and the old preference stayed in use. A "same" is now checked against the saved
value.

Steps 14 and 15 failed on their first run (2026-10-29), as on staging: the change was held as a conflict nobody was
asked about, the numbered preference stayed in use and the next summary came numbered. A change in the person's own
words now replaces even a confirmed memory; only a contradiction the model reports without one waits.
