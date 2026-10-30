// uc-259 a Summarise step summarises text, and an answer outside its schema takes the error port at once, ui layer:
// docs/usecases/agents-service/workflow-ai-steps.md. Priya, the team's admin, turns AI steps on in Govern › Policies
// and James publishes a notes workflow. One run's page ends Done with a summary on the Summarise step's sheet that
// keeps the name and date and masks the account; a broken answer's run ends Failed, its sheet showing error,
// schema_error and one attempt. Platform sign-in, fake model only.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { AI_STACK, JAMES, PASSWORD, PRIYA, aiDefinition, as, readRunPage, readStepSheet, saveAndPublish, settled, start, turnOnPolicy } from '../../lib/workflow_ui.mjs';

const ID = `uc259_notes_${Math.random().toString(36).slice(2, 6)}`;
const STEP = { id: 'sum', type: 'ops.ai.summarise', typeVersion: 1, parameters: { text: '$.input.body', maxWords: 40 } };
const DEFINITION = aiDefinition(ID, [STEP], [['start', 'payload', 'sum'], ['sum', 'ok', 'end_done'], ['sum', 'error', 'end_failed']]);

await withUiStack(async (consoleUrl, stack) => {
  const J = await as(JAMES);
  const browser = await chromium.launch();
  const errors = [];
  try {
    const turned = await turnOnPolicy(await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors), consoleUrl, 'aiSteps');
    const made = await saveAndPublish(J, DEFINITION);
    check('0 Priya turns AI steps on in Policies and the workflow publishes', turned === 200 && made.live, { policy: turned, live: made.live });
    await stack.startWorker();
    const done = await start(J, ID, { body: 'UC259-NOTE Priya Natarajan called: please close savings account 4471 by 30 November 2026.' }, { mode: 'live' });
    const broken = await start(J, ID, { body: 'UC259-BROKEN anything' }, { mode: 'live' });
    await settled(J, done);
    await settled(J, broken);

    const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
    const donePage = await readRunPage(page, consoleUrl, done);
    const summary = await readStepSheet(page, 'sum');
    check(
      "1 the run ends Done, and the Summarise step's sheet shows a summary that keeps the name and date, the account masked",
      donePage.outcome === 'done' && summary.port === 'ok' && /Priya Natarajan.*•{4}.*30 November 2026/.test(String(summary.output?.summary)),
      { outcome: donePage.outcome, sheet: summary },
    );
    const brokenPage = await readRunPage(page, consoleUrl, broken);
    const bad = await readStepSheet(page, 'sum');
    check(
      '2 an answer outside the schema ends Failed: the sheet shows error, schema_error and one attempt',
      brokenPage.outcome === 'failed' && bad.port === 'error' && bad.output?.code === 'schema_error' && bad.attempts === 1,
      { outcome: brokenPage.outcome, sheet: bad },
    );
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, AI_STACK);

finish();
