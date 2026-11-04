// uc-611 evidence, run by hand and never in the nightly run: the REST tool page against Stripe's API in test mode.
// Priya makes a Bearer connection with a Stripe test key through the API; James builds create_customer (a form body)
// and find_customers (`?email={email}`), runs both for real from the tool page, and the customer made comes back. The
// key comes from STRIPE_TEST_KEY, must be a test-mode key (sk_test_), and is never printed: the pages and the
// tools-service log are searched for it.
//
//   STRIPE_TEST_KEY=sk_test_... node docs/usecases/tools-service/scripts/evidence-uc-611-stripe.mjs
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, TOOLS_PORT, approveToolReview, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { CONNECTION_STACK, connection } from '../../lib/connection_ui.mjs';
import { JAMES, PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const KEY = process.env.STRIPE_TEST_KEY ?? '';
if (!KEY.startsWith('sk_test_')) {
  console.error('FAIL set STRIPE_TEST_KEY to a Stripe test-mode key (sk_test_...); a live key is refused');
  process.exit(1);
}
const RUN = Math.random().toString(36).slice(2, 6);
const EMAIL = `ops-ai-evidence+${RUN}@example.com`;
const STRIPE = 'https://api.stripe.com';
const tools = `http://127.0.0.1:${TOOLS_PORT}/v1/tool-modules`;
const shots = evidenceDir('591', 'stripe');

async function send(method, path, headers, body) {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${JSON.stringify(out.error ?? out).slice(0, 300)}`);
  return out.data;
}

async function run(page, moduleId) {
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/test`), { timeout: 60_000 });
  await page.getByTestId('run').click();
  const res = await answered;
  return { status: res.status(), ...((await res.json().catch(() => ({}))).data ?? {}) };
}

await withUiStack(
  async (consoleUrl) => {
    const sam = await as('s.adeyemi@harborpine.example', 'team_security');
    await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/egress/hosts`, { method: 'POST', headers: sam, body: JSON.stringify({ value: 'api.stripe.com', note: 'uc-611 evidence' }) });
    const J = await as(JAMES);
    const conn = await connection(await as(PRIYA), `Stripe test ${RUN}`, 'bearer', { sandbox: { secretValues: { token: KEY } } }, { baseUrl: STRIPE, testPath: '/v1/balance' });
    const mod = await send('POST', '/blank', J, { displayName: `Stripe ${RUN}`, name: `uc611-stripe-${RUN}`, type: 'http' });
    await send('PUT', `/${mod.id}/connection`, J, { connectionId: conn.id });
    await send('POST', `/${mod.id}/operations`, J, {
      name: 'create_customer', description: 'Creates a Stripe customer with an email.', access: 'write', method: 'POST',
      url: `${STRIPE}/v1/customers`, bodyEncoding: 'form', body: JSON.stringify({ email: '{{email}}', 'metadata[source]': 'ops_ai' }),
    }); // prettier-ignore
    await send('POST', `/${mod.id}/operations`, J, { name: 'find_customers', description: 'Stripe customers with an email.', access: 'read', method: 'GET', url: `${STRIPE}/v1/customers?email={email}` });
    await send('POST', `/${mod.id}/reviews`, J, { note: 'uc-611 evidence' });
    await approveToolReview(mod.id, await as('n.petrov@harborpine.example', 'team_security'), J);

    const browser = await chromium.launch();
    const errors = [];
    const seen = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await page.setViewportSize({ width: 1280, height: 900 });
      const real = async (op) => {
        await page.goto(`${consoleUrl}/tools/${mod.id}/operations/${op}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('run-mode').getByRole('radio', { name: 'Real' }).click({ timeout: 120_000 });
        await page.locator('#t-email').fill(EMAIL);
        const out = await run(page, mod.id);
        await page.getByTestId('run-badge').scrollIntoViewIfNeeded();
        seen.push(await page.locator('main').innerText());
        return out;
      };
      const made = await real('create_customer');
      await page.screenshot({ path: `${shots}/create-customer-real-1280-light.png` });
      check(
        '5 Stripe makes the test-mode customer from the tool page',
        made.status === 200 && /^cus_/.test(made.output?.id ?? '') && made.output?.email === EMAIL && made.output?.livemode === false,
        { status: made.status, id: made.output?.id, livemode: made.output?.livemode, error: made.output?.error?.code },
      );
      await page.getByRole('tab', { name: 'Request sent' }).click();
      seen.push(await page.getByTestId('test-request').innerText());
      await page.screenshot({ path: `${shots}/create-customer-request-sent-1280-light.png` });
      const found = await real('find_customers');
      await page.screenshot({ path: `${shots}/find-customers-real-1280-light.png` });
      check('7 the customer is found by email', found.status === 200 && (found.output?.data ?? []).some((c) => c.id === made.output?.id), { status: found.status, ids: (found.output?.data ?? []).map((c) => c.id) });
      const logs = readdirSync(join(ROOT, '.logs', 'usecase')).filter((f) => f.startsWith('tools-')).map((f) => readFileSync(join(ROOT, '.logs', 'usecase', f), 'utf8'));
      check('the key is on no page and in no log', ![...seen, ...logs].some((t) => t.includes(KEY)));
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  CONNECTION_STACK,
);

finish();
