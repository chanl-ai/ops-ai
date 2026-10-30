// uc-262 one workflow classifies, summarises, extracts and drafts on the fake model, ui layer:
// docs/usecases/agents-service/workflow-ai-steps.md. Priya, the team's admin, turns AI steps on in Govern › Policies
// and James publishes a dispute mail workflow of the four AI steps. Its run's page ends Disputed, and each step's sheet
// shows what it did: the fraud category, a summary with the amount, the fields read, and a reply about the dispute.
// Platform sign-in, fake model only.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { AI_STACK, JAMES, PASSWORD, PRIYA, aiDefinition, as, readRunPage, readStepSheet, saveAndPublish, settled, start, turnOnPolicy } from '../../lib/workflow_ui.mjs';

const ID = `uc262_dispute_mail_${Math.random().toString(36).slice(2, 6)}`;
const CATEGORIES = [
  { name: 'fraud', description: 'The customer reports a payment they did not make' },
  { name: 'billing', description: 'A question about fees or a statement' },
];
const STEPS = [
  { id: 'sort', type: 'ops.ai.classify', typeVersion: 1, parameters: { text: 'classify {$.input.body}', categories: CATEGORIES } },
  { id: 'gist', type: 'ops.ai.summarise', typeVersion: 1, parameters: { text: 'summary {$.input.body}' } },
  { id: 'facts', type: 'ops.ai.extractText', typeVersion: 1, parameters: { text: 'fields {$.input.body}', fields: [{ key: 'amount', type: 'money' }, { key: 'merchant' }, { key: 'date', type: 'date' }] } },
  { id: 'reply', type: 'ops.ai.draft', typeVersion: 1, parameters: { text: 'draft {$.input.body}', instructions: 'Tell the customer a dispute is open.' } },
];
const DEFINITION = aiDefinition(ID, STEPS, [
  ['start', 'payload', 'sort'],
  ['sort', 'fraud', 'gist'],
  ['sort', 'billing', 'end_billing'],
  ['sort', 'otherwise', 'end_person'],
  ['sort', 'error', 'end_failed'],
  ['gist', 'ok', 'facts'],
  ['gist', 'error', 'end_failed'],
  ['facts', 'ok', 'reply'],
  ['facts', 'error', 'end_failed'],
  ['reply', 'ok', 'end_disputed'],
  ['reply', 'error', 'end_failed'],
]);

await withUiStack(async (consoleUrl, stack) => {
  const J = await as(JAMES);
  const browser = await chromium.launch();
  const errors = [];
  try {
    const turned = await turnOnPolicy(await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors), consoleUrl, 'aiSteps');
    const made = await saveAndPublish(J, DEFINITION);
    check('0 Priya turns AI steps on in Policies and the workflow publishes', turned === 200 && made.live, { policy: turned, live: made.live });
    await stack.startWorker();
    const runId = await start(J, ID, { body: 'UC262-MAIL Hi, I did not pay Acme 900.00 on 14 October. Ann Lee' }, { mode: 'live' });
    await settled(J, runId);

    const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
    const shown = await readRunPage(page, consoleUrl, runId);
    const sheets = {};
    // Each sheet from a fresh load of the run page: a second sheet opened over a closing one is not drawn. A step
    // the run never reached has no row, so it has no sheet.
    for (const node of ['sort', 'gist', 'facts', 'reply']) {
      if (node !== 'sort') await readRunPage(page, consoleUrl, runId);
      sheets[node] = shown.count(node) ? await readStepSheet(page, node) : { port: '', output: undefined };
    }
    check('1 the run ends Disputed, and the Classify sheet shows it left by fraud', shown.outcome === 'disputed' && sheets.sort.port === 'fraud' && sheets.sort.output?.category === 'fraud', { outcome: shown.outcome, sort: sheets.sort });
    check("2 the Summarise sheet's summary keeps the amount", String(sheets.gist.output?.summary).includes('900.00'), sheets.gist);
    check(
      "3 the Extract sheet shows the fields read",
      JSON.stringify(sheets.facts.output) === JSON.stringify({ amount: 900, merchant: 'Acme', date: '2026-10-14' }),
      sheets.facts,
    );
    check("4 the Draft sheet's reply is about the dispute", String(sheets.reply.output?.body).includes('dispute'), sheets.reply);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, AI_STACK);

finish();
