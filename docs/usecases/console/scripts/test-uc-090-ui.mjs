// uc-090 a builder edits an operation's input, access and approval policy and sees its secrets, ui layer:
// docs/usecases/console/edit-an-operation.md. Signed in through platform-service as the seeded people. A published
// module with one read and one write is set up through the API; every edit below is made in the console.
import { PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = 'rates.bank.test';
const READ = `get_rate_${TAG}`;
const WRITE = `place_fx_hold_${TAG}`;
const SECRET = `RATES_KEY_${TAG.toUpperCase()}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = async (email, team) => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 300));
    return undefined;
  }
}

await withUiStack(
  async (consoleUrl) => {
    const SAM = await as('s.adeyemi@northfieldbank.com', 'team_security');
    const J = await as('j.richardson@northfieldbank.com', 'team_ops');
    const N = await as('n.petrov@northfieldbank.com', 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: SAM, body: JSON.stringify({ value: HOST, note: 'uc-090' }) });
    const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Rates ${TAG}`, name: `uc090-rates-${TAG}`, type: 'http' }) }))).id;
    const add = (body) => fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify(body) }).then(json);
    await add({ name: READ, description: 'A rate', access: 'read', method: 'GET', url: `https://${HOST}/v1/rates/{currency}`, headers: [{ key: 'X-Api-Key', value: `{{${SECRET}}}` }] });
    await add({ name: WRITE, description: 'Hold an FX quote', access: 'write', method: 'POST', url: `https://${HOST}/v1/holds`, headers: [] });
    await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-090' }) }));
    await approveToolReview(id, N);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // The row opens the operation's workbench (c-088): its input is edited there, and its access, approval and
      // secrets in the policy sheet the workbench opens.
      const sheet = async (op) => {
        await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByRole('row', { name: new RegExp(op) });
        await row.waitFor({ timeout: 120_000 });
        await row.click();
        await page.getByTestId('input-schema-editor').waitFor({ timeout: 30_000 });
      };
      const policy = async () => {
        await page.getByTestId('workbench-policy').click();
        await page.getByTestId('op-stage').waitFor({ timeout: 30_000 });
      };
      const stage = async (button = 'workbench-stage') => {
        const staged = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/tool-modules/${id}/operations/`), { timeout: 60_000 }));
        await page.getByTestId(button).click();
        const res = await staged;
        return { res, sent: res ? JSON.parse(res.request().postData() ?? '{}') : {}, body: res ? await res.json() : {} };
      };

      // 1. The module list warns that a secret its operations read is not set (T006).
      await step('1 the module list says one secret is not set', async () => {
        await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const warn = page.getByTestId(`unset-secrets-${id}`);
        const shown = await warn.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check('1 the module list says one secret is not set', shown && (await warn.innerText()) === '1 secret not set', { shown, text: shown ? await warn.innerText() : null });
      });

      // 2. The read's sheet names the secret its header reads, as not set, linking to Settings (T006).
      await step('2 the operation sheet names the secret as not set', async () => {
        await sheet(READ);
        await policy();
        const link = page.getByTestId('op-secrets').getByRole('link', { name: `${SECRET} not set` });
        const shown = await link.waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check('2 the operation sheet names the secret as not set', shown && (await link.getAttribute('href')) === '/settings/secrets', { shown });
      });

      // 3. A default that is not the field's type is refused, and the reason shows on that field (T002, T005).
      await step('3 a default of the wrong type is refused on its field', async () => {
        await sheet(READ);
        await page.getByTestId('input-add-field').click();
        await page.getByLabel('Field 2 name').fill('days');
        await page.getByLabel('Field 2 type').click();
        await page.getByRole('option', { name: 'integer', exact: true }).click();
        await page.getByLabel('Field 2 default').fill('ten');
        const { res, body } = await stage();
        const shown = await page.getByTestId('input-field-1').getByText('the default must be').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check('3 a default of the wrong type is refused on its field', res?.status() === 422 && body.error?.details?.field === 'input.days' && shown, { status: res?.status(), error: body.error, shown });
      });

      // 4. A new optional field with allowed values and no default is a minor change; a default would be sent for the
      // agent, so it would be major (T001, T005).
      await step('4 an optional field with allowed values stages as a minor change', async () => {
        await page.getByLabel('Field 2 type').click();
        await page.getByRole('option', { name: 'string', exact: true }).click();
        await page.getByLabel('Field 2 name').fill('tier');
        await page.getByLabel('Field 2 allowed values').fill('retail, wholesale');
        await page.getByLabel('Field 2 default').fill('');
        const { res, sent, body } = await stage();
        const field = sent.input?.find((f) => f.name === 'tier');
        const change = body.data?.pendingChanges?.find((c) => c.operation === READ && c.kind === 'schema_changed');
        check('4 an optional field with allowed values stages as a minor change', res?.status() === 200 && field?.default === undefined && field?.enum?.join() === 'retail,wholesale' && change?.major === false, { status: res?.status(), field, change });
      });

      // 5. A new required field is major, and the publish dialog says so (T001).
      await step('5 a new required field is major and the publish dialog says so', async () => {
        await sheet(READ);
        await page.getByTestId('input-add-field').click();
        await page.getByLabel('Field 3 name').fill('branch');
        await page.getByLabel('Field 3 required').click();
        const { res, body } = await stage();
        const change = body.data?.pendingChanges?.find((c) => c.operation === READ && c.kind === 'schema_changed');
        await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Publish version' }).click({ timeout: 60_000 });
        const major = await page.getByRole('dialog', { name: 'Publish a major version?' }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        await page.keyboard.press('Escape');
        check('5 a new required field is major and the publish dialog says so', res?.status() === 200 && change?.major === true && /branch added \(required\)/.test(change?.detail ?? '') && major, { status: res?.status(), change, major });
      });

      // 6. The write asks for a step-up, and the read becomes a write; both are major (T004, T006).
      await step('6 step-up on the write and an access change on the read stage as major', async () => {
        await sheet(WRITE);
        await policy();
        await page.getByRole('switch', { name: 'Approving asks for a step-up' }).click();
        const first = await stage('op-stage');
        await sheet(READ);
        await policy();
        await page.getByLabel('Access', { exact: true }).click();
        await page.getByRole('option', { name: 'Write', exact: true }).click();
        const second = await stage('op-stage');
        const ops = Object.fromEntries((second.body.data?.operations ?? []).map((o) => [o.name, o]));
        const access = second.body.data?.pendingChanges?.find((c) => c.operation === READ && c.kind === 'access_widened');
        check(
          '6 step-up on the write and an access change on the read stage as major',
          first.res?.status() === 200 && first.sent.stepUp === true && second.res?.status() === 200 && second.sent.access === 'write' && ops[WRITE]?.stepUp === true && ops[READ]?.access === 'write' && ops[READ]?.requiresApproval === true && access?.major === true,
          { stepUp: first.sent, access: second.sent, change: access },
        );
      });

      // 7. Once the secret is set the sheet says so and the list stops warning (T006).
      await step('7 setting the secret clears both warnings', async () => {
        await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: SAM, body: JSON.stringify({ name: SECRET, value: 'k-uc090' }) });
        await sheet(READ);
        await policy();
        const set = await page.getByTestId('op-secrets').getByText('Set', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('row', { name: new RegExp(`Rates ${TAG}`) }).waitFor({ timeout: 60_000 });
        const warning = await page.getByTestId(`unset-secrets-${id}`).count();
        check('7 setting the secret clears both warnings', set && warning === 0, { set, warning });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
