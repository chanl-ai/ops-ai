# UI QA: one console section at a time

Status: current. How a person or an agent checks one section of the console in a real browser for what works, how easy
it is, and how it looks. The look rules it checks against are in [standards.md](standards.md); this page is the pass.

## The pass

| Step | What to do |
|---|---|
| 1. Pick one section | One sidebar area per pass, for example Human Tasks. List its pages and every action on them before clicking anything |
| 2. Use a QA team | Sign in to a team kept for testing, never the demo team, so records the pass makes do not show in demos |
| 3. Do each job a person does there | Create, read, edit, run, decide, delete. Use the [use cases per area](../usecases/README.md) as the job list; add any job the page offers that no use case names |
| 4. Watch while doing it | Keep the browser's network and console open. Note every response that is not 2xx, every console error, and every action that takes over 1 second |
| 5. Look at every state | Each page loaded, empty, mid-action, after an error, at 1280 px and 375 px, light and dark |
| 6. Write each issue down | One row per issue in the findings table below, with a screenshot |
| 7. Rank and hand over | The top five issues go to the product owner explained in plain words; they choose what gets fixed |

## What to check

| Area | Check | Fails when |
|---|---|---|
| Works | Each action finishes and the result shows where a person expects it | A button does nothing, a save is lost, a list does not update, or a step needs a reload |
| Works | Errors come back as plain sentences | A raw exception, an error code alone, or "Something went wrong" with no next step |
| Works | Speed | A page or action takes over 1 second without a loading state, or over 3 seconds at all |
| Easy | The page says what it is for and what to do next | A person has to guess which button starts the job, or where the result went |
| Easy | Words are the person's, not the system's | Field keys ("ssn_last4"), ids, enum values or internal names shown as labels |
| Easy | Choices are offered, not typed | A free-text box where the answer is one of a few values, or an id the person cannot know |
| Easy | Destructive actions are guarded and explained | Delete or decide happens without saying what it affects; or it is guarded so heavily that the normal job is slow |
| Easy | Decisions show their context | A reviewer is asked to approve without seeing what, for whom, why and what happens next |
| Easy | Lists help find the one record | No search or filter on a list that grows; duplicate-looking rows that cannot be told apart |
| Looks | Layout follows [standards.md](standards.md) | Text overflows or wraps mid-word, columns squeeze values into strips, the page scrolls sideways on a phone |
| Looks | States are designed | A spinner alone, a blank area, an empty list with no action |
| Looks | Consistency | The same thing looks or reads differently on two pages (badges, dates, names, amounts) |

## Findings table

| # | Page | What happened | Why it matters | Severity | Screenshot |
|---|---|---|---|---|---|
| | | | | High / Medium / Low | |

High means a person cannot finish the job or would be misled. Medium means they can finish but it is slow or
confusing. Low means it looks wrong but does not get in the way.
