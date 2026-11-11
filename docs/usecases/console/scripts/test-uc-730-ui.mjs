// uc-730 a first-time admin decides what happens when an agent changes an app with one switch, ui layer.
// Platform sign-in as Priya Shah, admin of Operations, whose team has saved no approval setting. Govern › Approvals
// shows one switch, off, and asks who answers only once it is on; the five old approval rows are no longer on Policies.
import { check, chromium, finish, consoleSignIn, withUiStack } from '@ops-ai/usecase-runner/harness';

const SWITCH = /Ask before an agent changes anything in an app/i;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  const errors = [];
  try {
    const page = await consoleSignIn(browser, consoleUrl, 'p.shah@harborpine.example', 'northfield-demo', errors);
    page.setDefaultTimeout(30_000);

    await step('1 Approvals shows one switch, off, and no question about who answers', async () => {
      await page.goto(`${consoleUrl}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const switches = page.getByRole('switch');
      await switches.first().waitFor();
      const names = await switches.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') || e.textContent || ''));
      const only = page.getByRole('switch', { name: SWITCH });
      check('exactly one switch, the team switch', (await switches.count()) === 1 && (await only.count()) === 1, names);
      check('it is off', (await only.getAttribute('aria-checked')) === 'false');
      check('the choice of who answers is not shown while it is off', (await page.getByText(/Ask a reviewer/i).count()) === 0);
    });

    await step('2 Turning it on asks who answers, with the person chosen', async () => {
      await page.getByRole('switch', { name: SWITCH }).click();
      await page.getByText(/Ask a reviewer/i).first().waitFor();
      const person = page.getByRole('radio', { name: /Ask the person/i });
      check('Ask the person is chosen first', (await person.isChecked()) === true);
    });

    await step('3 Policies no longer holds the old approval rows', async () => {
      await page.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByText('Requester may decide').first().waitFor();
      const old = await page.getByText(/Approve every tool write|Approve writes of these apps|Apps that change without asking/i).count();
      check('the three approval rows moved to Approvals', old === 0, old);
    });

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, { platform: true, demo: true });
finish();
