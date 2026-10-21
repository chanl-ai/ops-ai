// uc-137 a changed publish review setting applies to the next tool module publish, ui layer:
// docs/usecases/console/publish-review-applies-at-once.md (c-139 T008, c-214). Platform sign-in. Priya is Operations'
// admin and sets the Tool modules review in the console; James publishes his module's minor changes in the console; no
// service restarts between the two settings.
import { PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = 'rates.bank.test';
const OP = `get_rate_${TAG}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = async (email, team) => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const SAM = await as('s.adeyemi@harborpine.example', 'team_security');
    const J = await as('j.richardson@harborpine.example', 'team_ops');
    const N = await as('n.petrov@harborpine.example', 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: SAM, body: JSON.stringify({ value: HOST, note: 'uc-137' }) });
    const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Rates ${TAG}`, name: `uc137-rates-${TAG}`, type: 'http' }) }))).id;
    await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: OP, description: 'A rate', access: 'read', method: 'GET', url: `https://${HOST}/v1/rates/{currency}`, headers: [] }) }));
    await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-137 first version' }) }));
    await approveToolReview(id, N);
    // A minor change staged through the API: a new description for the read, which touches no call shape or policy.
    const stage = async (description) => {
      const m = await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }));
      const op = m.operations.find((o) => o.name === OP);
      await json(await fetch(`${tools}/v1/tool-modules/${id}/operations/${op.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ description }) }));
    };

    const browser = await chromium.launch();
    const errors = [];
    try {
      const priya = await signIn(browser, consoleUrl, 'p.shah@harborpine.example', errors);
      const james = await signIn(browser, consoleUrl, 'j.richardson@harborpine.example', errors);
      const setTools = async (label) => {
        await priya.goto(`${consoleUrl}/settings/policies/publish-reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await priya.getByLabel('Tool modules review').click({ timeout: 120_000 });
        await priya.getByRole('option', { name: label }).click();
        const saved = priya.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes('/v1/policies/publishReview'), { timeout: 60_000 });
        await priya.getByRole('button', { name: 'Save' }).first().click();
        return (await saved).status();
      };
      const publish = async (note) => {
        await james.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByRole('button', { name: 'Publish version' }).click({ timeout: 120_000 });
        await james.getByLabel('What changed').fill(note);
        const done = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes(`/v1/tool-modules/${id}/`) && /publish|versions/.test(r.url()), { timeout: 60_000 });
        await james.getByRole('dialog').getByRole('button', { name: 'Publish', exact: true }).click();
        const status = (await done).status();
        const toast = (await james.locator('[data-sonner-toast]').first().innerText({ timeout: 30_000 })).trim();
        return { status, toast };
      };

      const never = await setTools('Publish at once');
      await stage(`A rate, as of ${TAG}`);
      const atOnce = await publish('Clearer description');
      check('1 with Tool modules set to Publish at once, a minor change publishes on the next publish', never === 200 && atOnce.status < 300 && /^Published /.test(atOnce.toast), { never, atOnce });

      const always = await setTools('Review every change');
      await stage(`A rate in the quote currency, ${TAG}`);
      const held = await publish('Names the currency');
      check('2 switched to Review every change, the very next publish waits for review, with no restart', always === 200 && held.status < 300 && /^Sent .* for review/.test(held.toast), { always, held });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);
finish();
