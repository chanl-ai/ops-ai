// uc-730 a first-time admin decides what happens when an agent changes an app with one switch, ui layer.
// Platform sign-in as Priya Shah, admin of Operations, whose team has saved no approval setting. Govern › Approvals
// shows one switch, off, and asks who answers only once it is on; the old approval rows and "Requester may decide" are no
// longer on Policies. "People can approve their own requests" shows only while a reviewer answers, and Advanced holds the
// "Test accounts never ask" checkbox, which is on until a team saves it off.
import { check, chromium, finish, consoleSignIn, withUiStack } from '@ops-ai/usecase-runner/harness';

const SWITCH = /Ask before an agent changes anything in an app/i;
const OWN = /People can approve their own requests/i;
const TEST_ACCOUNTS = /Test accounts never ask/i;

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
      check('1 exactly one switch, the team switch', (await switches.count()) === 1 && (await only.count()) === 1, names);
      check('1 it is off', (await only.getAttribute('aria-checked')) === 'false');
      check('1 the choice of who answers is not shown while it is off', (await page.getByText(/Ask a reviewer/i).count()) === 0);
      check('1 self-approval is not shown while it is off', (await page.getByRole('checkbox', { name: OWN }).count()) === 0);
    });

    await step('2 Turning it on asks who answers, with the person chosen', async () => {
      await page.getByRole('switch', { name: SWITCH }).click();
      await page.getByText(/Ask a reviewer/i).first().waitFor();
      const person = page.getByRole('radio', { name: /Ask the person/i });
      check('2 Ask the person is chosen first', (await person.isChecked()) === true);
      check('2 self-approval is not shown while the person answers', (await page.getByRole('checkbox', { name: OWN }).count()) === 0);
      await page.getByRole('radio', { name: /Ask a reviewer/i }).click();
      const own = page.getByRole('checkbox', { name: OWN });
      await own.waitFor();
      check('2 self-approval shows once a reviewer answers, off', (await own.getAttribute('aria-checked')) === 'false');
    });

    await step('3 Advanced holds Test accounts never ask, on until a team saves it off', async () => {
      await page.getByTestId('approvals-advanced').click();
      const box = page.getByRole('checkbox', { name: TEST_ACCOUNTS });
      await box.waitFor();
      check('3 it is on by default', (await box.getAttribute('aria-checked')) === 'true');
      await box.click();
      await page.getByTestId('setting-approvals-test-accounts').getByRole('button', { name: 'Save' }).click();
      await page.getByText(/Saved/).first().waitFor();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('approvals-advanced').click();
      const again = page.getByRole('checkbox', { name: TEST_ACCOUNTS });
      await again.waitFor();
      check('3 it stays off after a reload', (await again.getAttribute('aria-checked')) === 'false');
      await again.click();
      await page.getByTestId('setting-approvals-test-accounts').getByRole('button', { name: 'Save' }).click();
      await page.getByText(/Saved/).first().waitFor();
    });

    await step('4 Policies no longer holds the old approval rows or Requester may decide', async () => {
      const refused = [];
      const watch = (r) => {
        if (r.url().includes('/api/') && r.status() >= 400) refused.push(`${r.status()} ${new URL(r.url()).pathname}`);
      };
      page.on('response', watch);
      await page.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByText('Private chat threads').first().waitFor();
      await page.waitForLoadState('networkidle');
      page.off('response', watch);
      check('4 the Policies page makes no request that is refused or missing', refused.length === 0, refused);
      const old = await page.getByText(/Approve every tool write|Approve writes of these apps|Apps that change without asking|Requester may decide/i).count();
      check('4 the approval rows moved to Approvals', old === 0, old);
    });

    await step('5 A saved self-approval choice survives a reload', async () => {
      await page.goto(`${consoleUrl}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('switch', { name: SWITCH }).click();
      await page.getByRole('radio', { name: /Ask a reviewer/i }).click();
      await page.getByRole('combobox', { name: 'Reviewer role' }).click();
      await page.getByRole('option').first().click();
      await page.getByRole('checkbox', { name: OWN }).click();
      await page.getByTestId('setting-approvals-team').getByRole('button', { name: 'Save' }).click();
      await page.getByText(/Saved: Ask before/).first().waitFor();
      await page.reload({ waitUntil: 'domcontentloaded' });
      const own = page.getByRole('checkbox', { name: OWN });
      await own.waitFor();
      check('5 self-approval is still on after a reload', (await own.getAttribute('aria-checked')) === 'true');
    });

        await step('6 A member reads who can change a setting, with the right article', async () => {
      const member = await consoleSignIn(browser, consoleUrl, 'r.menon@harborpine.example', 'northfield-demo', errors);
      await member.goto(`${consoleUrl}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const lock = member.getByTestId('setting-lock').first();
      await lock.waitFor();
      const text = ((await lock.textContent()) ?? '').replace(/\s+/g, ' ').trim();
      check('6 the lock names an admin with "an", never "a Admin"', /Only an? (admin|Admin|team admin)/i.test(text) && !/\ba Admin\b/.test(text), text);
    });

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, { platform: true, demo: true });
finish();
