// uc-403 a workflow waits for a time or date and reminds a person, ui layer:
// docs/usecases/agents-service/wait-and-reminders.md. James saves the api script's three workflows; each run is read
// from its console page: the two-second Wait shows waiting and then Done, the date Wait's two outcomes, a review's
// reminders in Activity, and Priya (a team admin) deciding it in Human Tasks, after which no reminder follows. Platform sign-in, no
// model call.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, PRIYA, as, decideInConsole, readRunPage, saveAndPublish, settled, start, until } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const PAUSE = `
schemaVersion: 2
id: uc403_pause_${TAG}
name: Pause two seconds (uc-403)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Start}
  - {id: pause, type: ops.flow.wait, typeVersion: 1, name: Pause, parameters: {seconds: 2}}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: pause, port: in}}
  - {from: {node: pause, port: out}, to: {node: done, port: in}}
`;
const DUE = `
schemaVersion: 2
id: uc403_due_${TAG}
name: Wait for the response date (uc-403)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Levy}
  - id: due
    type: ops.flow.wait
    typeVersion: 1
    name: Until the response date
    parameters: {mode: until, until: "$.input.respondBy"}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Due, parameters: {outcome: due}}
  - {id: bad, type: ops.flow.end, typeVersion: 1, name: Not a date, parameters: {outcome: not_a_date}}
connections:
  - {from: {node: start, port: payload}, to: {node: due, port: in}}
  - {from: {node: due, port: out}, to: {node: done, port: in}}
  - {from: {node: due, port: error}, to: {node: bad, port: in}}
`;
const REMIND = `
schemaVersion: 2
id: uc403_remind_${TAG}
name: Check the levy, reminded (uc-403 ${TAG})
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Levy}
  - id: check
    type: ops.flow.humanReview
    typeVersion: 1
    name: Check the levy
    parameters: {title: Check the levy ${TAG}, remindEveryHours: 0.0006}
  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}
  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}
connections:
  - {from: {node: start, port: payload}, to: {node: check, port: in}}
  - {from: {node: check, port: approve}, to: {node: approved, port: in}}
  - {from: {node: check, port: reject}, to: {node: rejected, port: in}}
`;

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    const made = await Promise.all([PAUSE, DUE, REMIND].map((y) => saveAndPublish(J, y)));
    check('0 the three workflows save and go live', made.every((m) => m.saved.status === 201 && m.live), made.map((m) => [m.id, m.saved.status, m.asked.data?.status]));
    const [pause, due, remind] = made.map((m) => m.id);
    await stack.startWorker();

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const began = Date.now();
      const paused = await start(J, pause, {});
      await settled(J, paused, { orWaiting: true, seconds: 10 });
      const waitingPage = await readRunPage(page, consoleUrl, paused);
      const finished = await settled(J, paused, { seconds: 30 });
      const donePage = await readRunPage(page, consoleUrl, paused);
      check(
        '1 the two-second Wait shows waiting on its page, then Done, no sooner than two seconds after it started',
        /waiting|running/i.test(waitingPage.status) && finished?.outcome === 'done' && donePage.outcome === 'done' && Date.now() - began >= 2000,
        { first: waitingPage.status, then: donePage.status, outcome: donePage.outcome },
      );

      const past = await start(J, due, { respondBy: '2020-01-31' });
      const junk = await start(J, due, { respondBy: 'next Friday' });
      await settled(J, past, { seconds: 15 });
      await settled(J, junk, { seconds: 15 });
      const [pastPage, junkPage] = [await readRunPage(page, consoleUrl, past), await readRunPage(page, consoleUrl, junk)];
      check(
        '2 a past date goes on at once, and a value that is not a date ends Not a date, each on its run page',
        pastPage.outcome === 'due' && junkPage.outcome === 'not_a_date' && junkPage.count('bad') === 1,
        { past: pastPage.outcome, junk: junkPage.outcome, steps: junkPage.steps.map((s) => s.nodeId) },
      );

      const reminded = await start(J, remind, {});
      const rows = async () => {
        await page.goto(`${consoleUrl}/activity?kind=reminder`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('row').nth(1).waitFor({ timeout: 30_000 }).catch(() => undefined);
        return page.getByRole('row').filter({ hasText: `Check the levy ${TAG}` }).count();
      };
      // Reminders come about every two seconds; the page is read again until two are listed.
      const two = await until(async () => ((await rows()) >= 2 ? await rows() : undefined), 40);
      const waiting = await settled(J, reminded, { orWaiting: true, seconds: 5 });
      check('3 a review left waiting is reminded, the reminders are listed in Activity, and the run keeps waiting', (two ?? 0) >= 2 && waiting?.status === 'waiting', { listed: two, run: waiting?.status });

      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const decided = await decideInConsole(priya, consoleUrl, waiting);
      const approved = await settled(J, reminded, { seconds: 20 });
      const count = await rows();
      await new Promise((r) => setTimeout(r, 4000));
      const later = await rows();
      const after = await readRunPage(page, consoleUrl, reminded);
      check(
        '4 Priya approves in Human Tasks, the run page shows it approved, and no reminder follows',
        decided === 200 && approved?.outcome === 'approved' && after.outcome === 'approved' && later === count,
        { decided, outcome: after.outcome, before: count, after: later },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
