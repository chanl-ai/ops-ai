// uc-261 a Draft step writes a reply and sends nothing, ui layer: docs/usecases/agents-service/workflow-ai-steps.md.
// Priya, the team's admin, turns AI steps on in Govern › Policies and James publishes a reply workflow. Its run's
// page ends Drafted, the Draft step's sheet shows a subject and a body that says what happens and by when, and the
// Steps table lists only the draft and its end: nothing was sent. Platform sign-in, fake model only.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { AI_STACK, JAMES, PASSWORD, PRIYA, aiDefinition, as, readRunPage, readStepSheet, saveAndPublish, settled, start, turnOnPolicy } from '../../lib/workflow_ui.mjs';

const ID = `uc261_reply_${Math.random().toString(36).slice(2, 6)}`;
const STEP = {
  id: 'reply',
  type: 'ops.ai.draft',
  typeVersion: 1,
  parameters: { text: '$.input.body', instructions: 'Reply to the customer; confirm what we will do and by when.' },
};
const DEFINITION = aiDefinition(ID, [STEP], [['start', 'payload', 'reply'], ['reply', 'ok', 'end_drafted'], ['reply', 'error', 'end_failed']]);

await withUiStack(async (consoleUrl, stack) => {
  const J = await as(JAMES);
  const browser = await chromium.launch();
  const errors = [];
  try {
    const turned = await turnOnPolicy(await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors), consoleUrl, 'aiSteps');
    const made = await saveAndPublish(J, DEFINITION);
    check('0 Priya turns AI steps on in Policies and the workflow publishes', turned === 200 && made.live, { policy: turned, live: made.live });
    await stack.startWorker();
    const runId = await start(J, ID, { body: 'UC261-REPLY Please close my account 4471 by the end of November. Priya' }, { mode: 'live' });
    await settled(J, runId);

    const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
    const shown = await readRunPage(page, consoleUrl, runId);
    const sheet = await readStepSheet(page, 'reply');
    check(
      "1 the run ends Drafted, and the Draft step's sheet shows a subject and a body that says what happens and when",
      shown.outcome === 'drafted' && sheet.port === 'ok' && !!sheet.output?.subject && String(sheet.output?.body).includes('30 November'),
      { outcome: shown.outcome, sheet },
    );
    const ran = shown.steps.map((s) => s.nodeId).filter((n) => n !== 'start').sort();
    check('2 the Steps table lists only the draft and its end: nothing was sent', ran.join() === 'end_drafted,reply', shown.steps);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, AI_STACK);

finish();
