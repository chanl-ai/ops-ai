// uc-258 a Classify step routes a message by meaning, ui layer: docs/usecases/agents-service/workflow-ai-steps.md.
// With AI steps off James's triage workflow is refused; Priya, the team's admin, turns them on in Govern › Policies,
// and it publishes. Each run's console page shows where the message went: a confident fraud answer ends Fraud with
// the Classify step's category on its sheet, and an unsure one leaves by otherwise for a person. Platform sign-in,
// fake model only.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, PRIYA, as, readRunPage, readStepSheet, saveAndPublish, settled, start, turnOnPolicy } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const ID = `uc258_triage_${TAG}`;
const end = (id) => ({ id, type: 'ops.flow.end', typeVersion: 1, parameters: { outcome: id.slice(4) } });
const DEFINITION = {
  schemaVersion: 2,
  id: ID,
  name: `Triage by meaning ${TAG}`,
  nodes: [
    { id: 'start', type: 'ops.trigger.request', typeVersion: 1, parameters: {} },
    {
      id: 'sort',
      type: 'ops.ai.classify',
      typeVersion: 1,
      parameters: {
        text: '$.input.body',
        categories: [
          { name: 'fraud', description: 'The customer reports a payment they did not make' },
          { name: 'billing', description: 'A question about fees or a statement' },
        ],
        minConfidence: 0.6,
      },
    },
    ...['end_billing', 'end_failed', 'end_fraud', 'end_person'].map(end),
  ],
  connections: [
    ['start', 'payload', 'sort'],
    ['sort', 'fraud', 'end_fraud'],
    ['sort', 'billing', 'end_billing'],
    ['sort', 'otherwise', 'end_person'],
    ['sort', 'error', 'end_failed'],
  ].map(([f, p, t]) => ({ from: { node: f, port: p }, to: { node: t, port: 'in' } })),
};

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    const browser = await chromium.launch();
    const errors = [];
    try {
      const refused = await saveAndPublish(J, DEFINITION);
      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const turned = await turnOnPolicy(priya, consoleUrl, 'aiSteps');
      const made = await saveAndPublish(J, DEFINITION);
      check(
        '1 with AI steps off the workflow is refused; Priya turns them on in Policies and it publishes',
        refused.saved.status === 422 && turned === 200 && made.live,
        { off: refused.saved.status, policy: turned, live: made.live, asked: made.asked.data?.status },
      );

      await stack.startWorker();
      const fraud = await start(J, ID, { body: 'UC258-FRAUD I never paid Acme 900 dollars on my card' }, { mode: 'live' });
      const unsure = await start(J, ID, { body: 'UC258-UNSURE Why is there a charge on my statement?' }, { mode: 'live' });
      await settled(J, fraud);
      await settled(J, unsure);

      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const fraudPage = await readRunPage(page, consoleUrl, fraud);
      const sorted = await readStepSheet(page, 'sort');
      check(
        "2 a confident answer ends Fraud, and the Classify step's sheet shows it left by fraud with the category",
        fraudPage.outcome === 'fraud' && sorted.port === 'fraud' && sorted.output?.category === 'fraud',
        { outcome: fraudPage.outcome, sheet: sorted },
      );
      const unsurePage = await readRunPage(page, consoleUrl, unsure);
      const left = await readStepSheet(page, 'sort');
      check(
        '3 an answer below the floor leaves by otherwise and ends with a person',
        unsurePage.outcome === 'person' && left.port === 'otherwise',
        { outcome: unsurePage.outcome, sheet: left },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, fakeModelRules: 'services/agents-service/tests/fixtures/ai-steps-fake-openai' },
);

finish();
