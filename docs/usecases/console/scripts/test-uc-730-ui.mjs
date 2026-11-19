// uc-730 a first-time admin decides what happens when an agent changes an app with one switch, ui layer.
// Platform sign-in as Wanjiru Kamau, admin of every team, whose team has saved no approval setting. Govern › Approvals
// shows one switch, off, and asks who answers only once it is on; the old approval rows and "Requester may decide" are no
// longer on Policies. "People can approve their own requests" shows only while a reviewer answers, and Advanced holds the
// "Test accounts never ask" checkbox, which is on until a team saves it off.
import { PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, consoleSignIn, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = async (email, team) => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

const SWITCH = /Ask before an agent changes anything in an app/i;
const OWN = /People can approve their own requests/i;
const TEST_ACCOUNTS = /Test accounts never ask/i;
const TEST_RUNS = /Test runs on live accounts ask first/i;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(async (consoleUrl, stack) => {
  const browser = await chromium.launch();
  const errors = [];
  try {
    const page = await consoleSignIn(browser, consoleUrl, 'w.kamau@harborpine.example', 'northfield-demo', errors);
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

    await step('3b Advanced holds Test runs on live accounts ask first, on until a team saves it off', async () => {
      await page.goto(`${consoleUrl}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('approvals-advanced').click();
      const box = page.getByRole('checkbox', { name: TEST_RUNS });
      await box.waitFor();
      check('3b it is on by default', (await box.getAttribute('aria-checked')) === 'true');
      await box.click();
      await page.getByTestId('setting-approvals-test-runs').getByRole('button', { name: 'Save' }).click();
      await page.getByText(/Saved: Test runs/).first().waitFor();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('approvals-advanced').click();
      const again = page.getByRole('checkbox', { name: TEST_RUNS });
      await again.waitFor();
      check('3b it stays off after a reload', (await again.getAttribute('aria-checked')) === 'false');
      await again.click();
      await page.getByTestId('setting-approvals-test-runs').getByRole('button', { name: 'Save' }).click();
      await page.getByText(/Saved: Test runs/).first().waitFor();
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

    // Runs before step 5: that step lets approvers approve their own requests, which would skip the card.
    await step('7 A test run of a write on a live account shows the approval card; no refuses it, yes runs it', async () => {
      // A published Operations module with one write, on the fake bank, and no account of its own: a live account.
      const S = await as('s.adeyemi@harborpine.example', 'team_security');
      const J = await as('j.richardson@harborpine.example', 'team_ops');
      const N = await as('n.petrov@harborpine.example', 'team_security');
      await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.bank.host, note: 'uc-730' }) });
      await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.bank.range, note: 'uc-730' }) });
      const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Holds ${TAG}`, name: `uc730-holds-${TAG}`, type: 'http' }) }))).id;
      const op = `place_hold_${TAG}`;
      await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: op, description: 'Place a hold', access: 'write', method: 'POST', url: `https://${stack.bank.host}/accounts/{account_id}/holds`, headers: [] }) }));
      await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-730' }) }));
      await approveToolReview(id, N, J);
      const james = await consoleSignIn(browser, consoleUrl, 'j.richardson@harborpine.example', 'northfield-demo', errors);
      await james.goto(`${consoleUrl}/tools/${id}/operations/${op}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const panel = james.getByTestId('module-test-panel');
      await panel.waitFor();
      const runs = [];
      james.on('request', (r) => {
        if (r.method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${id}/test`)) runs.push(r.postDataJSON());
      });
      const run = async () => {
        await panel.getByRole('radio', { name: 'Real' }).or(panel.getByRole('button', { name: 'Real' })).first().click();
        await panel.locator('#t-account_id').fill('CHQ-2219');
        const answered = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${id}/test`), { timeout: 60_000 });
        await panel.getByRole('button', { name: 'Run' }).click();
        return (await answered).json();
      };
      const first = await run();
      check('7 the first run is held for the person, nothing sent', first.data?.denyReason === 'approval_token_missing', first.data);
      const card = panel.getByTestId('ask-first-card');
      await card.waitFor({ timeout: 15_000 }).catch(async (e) => {
        throw new Error(`${e.message.split('\n')[0]} panel: ${(await panel.innerText()).replace(/\s+/g, ' ').slice(0, 600)}`);
      });
      check('7 the approval card shows Allow and Deny', (await card.getByTestId('ask-first-allow').count()) === 1 && (await card.getByTestId('ask-first-deny').count()) === 1);
      check('7 the card has no Allow for this chat', (await panel.getByTestId('ask-first-allow-chat').count()) === 0);
      await card.getByTestId('ask-first-deny').click();
      await panel.getByText('Denied', { exact: true }).first().waitFor();
      check('7 Deny sent no second run', runs.length === 1, runs.length);
      check('7 the denied card has no buttons left', (await card.getByTestId('ask-first-allow').count()) === 0);
      await panel.getByRole('button', { name: 'Run' }).click();
      await card.getByTestId('ask-first-allow').waitFor();
      const ran = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${id}/test`) && r.request().postDataJSON()?.confirmed === true, { timeout: 60_000 });
      await card.getByTestId('ask-first-allow').click();
      const yes = (await ran).json();
      const answer = await yes;
      // The fake bank answers this route 401 (no key on a blank module); what matters is that the gateway sent the write.
      check('7 Allow sends the write to the app', answer.data?.decision === 'allow' && answer.data?.stubbed === false && answer.data?.reachedHost === stack.bank.host && answer.data?.request?.method === 'POST', answer.data);
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
