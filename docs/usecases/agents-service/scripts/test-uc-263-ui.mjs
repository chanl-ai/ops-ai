// uc-263 a typed task opens with task assist when the team turns it on, ui layer:
// docs/usecases/agents-service/task-assist.md. With task assist off James's task opens for Maya, a reviewer, with no AI
// assist; Priya, the team's admin, turns it on in Govern › Policies, and the same task opens with the assist marked AI
// and its suggestion marked on Reject; a suggestion the type does not offer is dropped. Platform sign-in, fake model only.
import { AGENTS_PORT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, PRIYA, as, turnOnPolicy, until } from '../../lib/workflow_ui.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const FACTS = [{ label: 'Vendor', value: 'Acme' }, { label: 'New account', value: '****4410' }];

/** Posts a generic_decision task and returns it once its review can be read. */
async function post(J, title) {
  const res = await fetch(`${agents}/v1/tasks`, { method: 'POST', headers: J, body: JSON.stringify({ type: 'generic_decision', params: { title, facts: FACTS } }) });
  const task = (await res.json()).data;
  if (res.status !== 201) throw new Error(`opening the task answered ${res.status}: ${JSON.stringify(task).slice(0, 300)}`);
  await until(async () => (await fetch(`${agents}/reviews/${encodeURIComponent(task.id)}`, { headers: J })).ok);
  return task;
}

/** Opens the task in the console and reads its decide pane once the assist, when there is one, has been written. */
async function read(page, consoleUrl, task, assisted) {
  await page.goto(`${consoleUrl}${task.url}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const decide = page.getByTestId('task-decide');
  await decide.waitFor({ timeout: 60_000 }).catch(async (e) => {
    const shown = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 500);
    throw new Error(`no decide pane on ${page.url()} for ${task.url}: ${e.message.split('\n')[0]}; the page shows: ${shown}`);
  });
  // A pending assist shows "Writing a summary…" and the page reads it again until it lands.
  if (assisted) await decide.getByText('Summary').first().waitFor({ timeout: 90_000 }).catch(() => undefined);
  return {
    text: (await decide.innerText()).replace(/\s+/g, ' '),
    // The decision's options (option-<action>); the assist's pick carries a Suggested badge and is never chosen for the person.
    ...(await page.getByTestId('option-decision-form').locator('[data-testid^="option-"]').evaluateAll((els) => {
      const options = els.map((e) => ({ id: e.getAttribute('data-testid'), suggested: /Suggested/.test(e.textContent ?? ''), chosen: e.querySelector('[data-state="checked"]') !== null }));
      return { buttons: options.map((o) => o.id), suggested: options.filter((o) => o.suggested).map((o) => o.id), chosen: options.filter((o) => o.chosen).map((o) => o.id) };
    })),
  };
}

await withUiStack(
  async (consoleUrl, stack) => {
    // A task is a run of the api_task workflow: a worker takes it to its review.
    await stack.startWorker();
    const J = await as(JAMES);
    const browser = await chromium.launch();
    const errors = [];
    try {
      // James asks, so Maya decides: the asker sees no decision buttons on his own task.
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      const off = await read(page, consoleUrl, await post(J, "Change Acme's bank account? UC263-ASSIST"), false);
      check('1 with task assist off the task opens with no AI assist and nothing suggested', !/AI assist/.test(off.text) && off.buttons.includes('option-reject') && off.suggested.length === 0, off);

      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const turned = await turnOnPolicy(priya, consoleUrl, 'taskAssist');
      check('2 Priya turns task assist on in Policies (200)', turned === 200, turned);

      const on = await read(page, consoleUrl, await post(J, "Change Acme's bank account? UC263-ASSIST"), true);
      check(
        '3 the task opens with the AI assist: its question, summary and the field worth checking, and Reject marked as suggested, not chosen',
        /AI assist/.test(on.text) && /Should the Acme vendor's bank account change\?/.test(on.text) && /Worth checking New account/.test(on.text) && JSON.stringify(on.suggested) === JSON.stringify(['option-reject']) && on.chosen.length === 0,
        on,
      );

      const odd = await read(page, consoleUrl, await post(J, 'Open it? UC263-ODD'), true);
      check('5 a suggestion of an action the type does not offer is dropped: the assist shows and nothing is marked', /AI assist/.test(odd.text) && !/Suggests/.test(odd.text) && odd.buttons.length > 0 && odd.suggested.length === 0, odd);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, fakeModelRules: 'services/agents-service/tests/fixtures/ai-steps-fake-openai' },
);

finish();
