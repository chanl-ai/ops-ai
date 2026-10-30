// uc-260 an Extract from text step reads fields from a message, ui layer:
// docs/usecases/agents-service/workflow-ai-steps.md. Priya, the team's admin, turns AI steps on in Govern › Policies
// and James publishes a levy mail workflow. Its run's page ends Done, and the Extract step's sheet shows each field
// by its key, with the court the text never states as null. Platform sign-in, fake model only.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { AI_STACK, JAMES, PASSWORD, PRIYA, aiDefinition, as, readRunPage, readStepSheet, saveAndPublish, settled, start, turnOnPolicy } from '../../lib/workflow_ui.mjs';

const ID = `uc260_levy_mail_${Math.random().toString(36).slice(2, 6)}`;
const FIELDS = [
  { key: 'amount', label: 'Amount', type: 'money' },
  { key: 'case_no', label: 'Case number', type: 'text' },
  { key: 'court', label: 'Court', type: 'text' },
];
const STEP = { id: 'read', type: 'ops.ai.extractText', typeVersion: 1, parameters: { text: '$.input.body', fields: FIELDS } };
const DEFINITION = aiDefinition(ID, [STEP], [['start', 'payload', 'read'], ['read', 'ok', 'end_done'], ['read', 'error', 'end_failed']]);

await withUiStack(async (consoleUrl, stack) => {
  const J = await as(JAMES);
  const browser = await chromium.launch();
  const errors = [];
  try {
    const turned = await turnOnPolicy(await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors), consoleUrl, 'aiSteps');
    const made = await saveAndPublish(J, DEFINITION);
    check('0 Priya turns AI steps on in Policies and the workflow publishes', turned === 200 && made.live, { policy: turned, live: made.live });
    await stack.startWorker();
    const runId = await start(J, ID, { body: 'UC260-LEVY Please process the levy of 3,250.00 on case NS-2026-GN-01187.' }, { mode: 'live' });
    await settled(J, runId);

    const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
    const shown = await readRunPage(page, consoleUrl, runId);
    const sheet = await readStepSheet(page, 'read');
    check(
      "1 the run ends Done, and the Extract step's sheet shows each field by its key, the unstated court as null",
      shown.outcome === 'done' && sheet.port === 'ok' && JSON.stringify(sheet.output) === JSON.stringify({ amount: 3250, case_no: 'NS-2026-GN-01187', court: null }),
      { outcome: shown.outcome, sheet },
    );
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, AI_STACK);

finish();
