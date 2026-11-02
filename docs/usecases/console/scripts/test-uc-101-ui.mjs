// uc-101 a builder builds and debugs a REST tool on its own page, ui layer: docs/usecases/console/tool-workbench.md.
// Signed in through platform-service as the seeded people. A published module with the core bank's statement read (its
// key in the query string, as the fake's legacy route takes it) and a mock answer are set up through the API; everything
// after is clicked on the REST tool page (the API-client layout; functions keep the Function workbench). Each step is
// checked on its own.
import { PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const OP = `get_statement_${TAG}`;
const ACCOUNT = 'CHQ-2219';
// The fake bank's key (FAKE_BANK_KEY's default). It is typed for one run and never set as a tenant secret.
const BANK_KEY = 'dev-bank-key';
const JAMES = 'j.richardson@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
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
  async (consoleUrl, stack) => {
    const SAM = await as('s.adeyemi@harborpine.example', 'team_security');
    const J = await as(JAMES, 'team_ops');
    const N = await as('n.petrov@harborpine.example', 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: SAM, body: JSON.stringify({ value: stack.bank.host, note: 'uc-101' }) });
    await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: SAM, body: JSON.stringify({ value: stack.bank.range, note: 'uc-101' }) });
    const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Core bank ${TAG}`, name: `uc101-bank-${TAG}`, type: 'http' }) }))).id;
    await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: OP, description: 'The latest statement', access: 'read', method: 'GET', url: `https://${stack.bank.host}/accounts/{account_id}/statement?api_key={{STATEMENTS_API_KEY}}`, headers: [] }) }));
    await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-101' }) }));
    await approveToolReview(id, N, J);
    const opNow = async () => (await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }))).operations.find((o) => o.name === OP);
    // The operation's example answer, which Mock answers with and a Real run in Test never does: a balance to transform.
    await json(await fetch(`${tools}/v1/tool-modules/${id}/operations/${(await opNow()).id}/mocks`, { method: 'POST', headers: J, body: JSON.stringify({ name: 'statement', environment: 'example', default: true, status: 200, body: { accountId: ACCOUNT, closingBalance: 1520.33, lines: 4 } }) }));

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const panel = page.getByTestId('module-test-panel');
      const run = async () => {
        const ran = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${id}/test`), { timeout: 60_000 }));
        await panel.getByTestId('run').click();
        const res = await ran;
        return { res, body: res ? await res.text() : '', data: res ? (JSON.parse((await res.text()) || '{}').data ?? {}) : {} };
      };
      const tab = async (name) => {
        await panel.getByRole('tab', { name }).click();
        return panel.getByRole('tabpanel').last().innerText();
      };
      // Raw response, Log, Transform and Mock answers sit under the answer's More.
      const more = async (item) => {
        await panel.getByTestId('answer-more').click();
        await page.getByRole('menuitem', { name: item }).click();
      };

      // 1. A row of the operations table opens the operation on its own page; the module page has no side console.
      await step('1 the operation opens on its own full-width page', async () => {
        await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByRole('row', { name: new RegExp(OP) });
        await row.waitFor({ timeout: 120_000 });
        // The row is one tab stop: one link to the tool page in its name cell, and no tabindex on the row itself.
        const rowLinks = await row.locator(`a[href$="/operations/${OP}"]`).count();
        const rowTabindex = await row.getAttribute('tabindex');
        const sideConsole = await page.getByTestId('module-test-panel').count();
        await row.click();
        await page.waitForURL(`**/tools/${id}/operations/${OP}`, { timeout: 60_000 });
        const shown = await panel.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const width = shown ? (await panel.boundingBox())?.width ?? 0 : 0;
        check('1 the operation opens on its own full-width page', sideConsole === 0 && shown && width > 900 && rowLinks === 1 && rowTabindex === null, { sideConsole, shown, width, rowLinks, rowTabindex });
      });

      // 2. The mock answer and a draft transform run on Mock without saving; the operation agents call is unchanged.
      await step('2 a mock answer and a draft transform run without changing the operation', async () => {
        await more('Transform');
        await page.locator('#wb-transform').fill('{"balance": {{ data.closingBalance }}}');
        await page.getByRole('tab', { name: 'Inputs' }).click().catch(() => undefined);
        await panel.locator('#t-account_id').fill(ACCOUNT);
        const { res, data } = await run();
        const output = await tab('Response');
        await more('Raw response');
        const raw = await panel.getByRole('tabpanel').last().innerText();
        const op = await opNow();
        const detail = await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }));
        check(
          '2 a mock answer and a draft transform run without changing the operation',
          res?.status() === 200 && /"balance":\s*1520\.33/.test(output) && /closingBalance/.test(raw) && !op.responseTransform && detail.pendingChanges.length === 0,
          { status: res?.status(), output: output.slice(0, 120), raw: raw.slice(0, 120), transform: op.responseTransform ?? null, pending: detail.pendingChanges.length, log: data.log?.map((l) => l.message) },
        );
      });

      // 3. A secret value typed for one run reaches the bank; the request shows it masked, and nothing returns it.
      await step('3 a typed secret runs live and shows masked', async () => {
        await page.locator('#wb-transform').fill('');
        await page.getByRole('tab', { name: 'Headers' }).click();
        await page.getByLabel('STATEMENTS_API_KEY test value').fill(BANK_KEY);
        await panel.getByTestId('run-mode').getByRole('radio', { name: 'Real' }).click();
        const { res, body, data } = await run();
        const request = await tab('Request sent');
        const output = await tab('Response');
        const ok = await panel.getByText('Allowed').count();
        check(
          '3 a typed secret runs live and shows masked',
          res?.status() === 200 && data.status === 200 && ok > 0 && /api_key=(%5B|\[)secret/.test(request) && !request.includes(BANK_KEY) && !output.includes(BANK_KEY) && !body.includes(BANK_KEY),
          { status: data.status, request: request.slice(0, 240), leaked: body.includes(BANK_KEY) },
        );
      });

      // 3b. A value typed for one run leaves the page when the run ends. React writes a controlled input's value into its
      // `value` attribute, so a kept state keeps the secret in the page's HTML.
      await step('3b the typed secret is gone from the page once the run ends', async () => {
        await page.getByRole('tab', { name: 'Headers' }).click();
        const input = page.getByLabel('STATEMENTS_API_KEY test value');
        const kept = await input.inputValue();
        const attribute = await input.getAttribute('value');
        const inHtml = await page.evaluate((s) => document.documentElement.outerHTML.includes(s), BANK_KEY);
        check('3b the typed secret is gone from the page once the run ends', kept === '' && !attribute && !inHtml, { kept: kept ? 'still typed' : '', attribute, inHtml });
      });

      // 4. A transform that fails says why under the field and on the result; the response is the raw answer.
      await step('4 a failing transform shows its reason', async () => {
        await panel.getByTestId('run-mode').getByRole('radio', { name: 'Mock' }).click();
        await page.locator('#wb-transform').fill('{"b": {{ data.closing.balance }}}');
        await page.getByRole('tab', { name: 'Inputs' }).click().catch(() => undefined);
        await panel.locator('#t-account_id').fill(ACCOUNT);
        const { data } = await run();
        const onResult = await panel.getByTestId('test-transform-error').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const underField = await page.locator('#wb-transform').locator('xpath=ancestor::*[@data-slot="form-item" or contains(@class,"flex-col")][1]').innerText().catch(() => '');
        const output = await tab('Response');
        check(
          '4 a failing transform shows its reason',
          !!data.transformError && onResult && underField.includes('closing') && /closingBalance/.test(output),
          { transformError: data.transformError, onResult, underField: underField.slice(0, 160) },
        );
      });

      // 5. A saved transform is a change to publish, listed on the module.
      await step('5 a saved transform is listed as an unpublished change', async () => {
        await page.locator('#wb-transform').fill('{"balance": {{ data.closingBalance }}}');
        const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/tool-modules/${id}/operations/`), { timeout: 60_000 }));
        await page.getByTestId('workbench-stage').click();
        const res = await saved;
        const sent = res ? JSON.parse(res.request().postData() ?? '{}') : {};
        const detail = await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }));
        const change = detail.pendingChanges.find((c) => c.operation === OP);
        await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const listed = await page.getByText(/unpublished change/).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check('5 a saved transform is listed as an unpublished change', res?.status() === 200 && /closingBalance/.test(sent.responseTransform ?? '') && !!change && listed, { status: res?.status(), sent, change, listed });
      });

      // 6. A viewer opens the same page read-only and may still run it; a builder never sees the notice, not even while
      // the role loads.
      await step('6 a viewer sees the tool page read-only with Run off and why, and a builder never sees View only', async () => {
        const url = `${consoleUrl}/tools/${id}/operations/${OP}`;
        const open = async (email, watchNotice) => {
          const p = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
          p.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
          if (watchNotice) {
            await p.addInitScript(() => {
              window.__viewOnly = false;
              new MutationObserver(() => {
                if (document.body?.innerText.includes('View only')) window.__viewOnly = true;
              }).observe(document, { childList: true, subtree: true, characterData: true });
            });
          }
          await p.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await p.getByLabel('Email').fill(email);
          await p.getByLabel('Password').fill('northfield-demo');
          await p.getByRole('button', { name: /^Sign in/ }).first().click();
          await p.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
          await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await p.getByTestId('module-test-panel').waitFor({ timeout: 120_000 });
          return p;
        };
        const ravi = await open(RAVI, false);
        const notice = await ravi.getByTestId('read-only-notice').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const viewer = {
          notice,
          save: await ravi.getByTestId('workbench-stage').count(),
          policy: await ravi.getByTestId('workbench-policy').count(),
          appDisabled: await ravi.getByTestId('module-connection-select').isDisabled(),
          // A viewer may not run tools (tools.run): Run is off and the page says why, rather than answering a refusal.
          runEnabled: await ravi.getByTestId('run').isEnabled(),
          runWhy: ((await ravi.getByTestId('run-help').innerText().catch(() => '')) ?? '').includes('can’t run tools'),
        };
        const james = await open(JAMES, true);
        await james.getByTestId('workbench-stage').waitFor({ timeout: 30_000 });
        await james.waitForTimeout(1500);
        const builder = { save: await james.getByTestId('workbench-stage').count(), policy: await james.getByTestId('workbench-policy').count(), notice: await james.getByTestId('read-only-notice').count(), flashed: await james.evaluate(() => window.__viewOnly), appDisabled: await james.getByTestId('module-connection-select').isDisabled() };
        check(
          '6 a viewer sees the tool page read-only with Run off and why, and a builder never sees View only',
          viewer.notice && viewer.save === 0 && viewer.policy === 0 && viewer.appDisabled && !viewer.runEnabled && viewer.runWhy && builder.save === 1 && builder.policy === 1 && builder.notice === 0 && !builder.flashed && !builder.appDisabled,
          { viewer, builder },
        );
      });

      // 7. On a phone the page is one column: Run sits with the address, above the inputs, and nothing scrolls sideways.
      await step('7 on a phone Run is above the inputs and nothing scrolls sideways', async () => {
        await page.setViewportSize({ width: 390, height: 800 });
        await page.goto(`${consoleUrl}/tools/${id}/operations/${OP}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await panel.waitFor({ timeout: 120_000 });
        // Save shows once the role is known; until then the page lays Run out for a viewer.
        await page.getByTestId('workbench-stage').waitFor({ timeout: 60_000 });
        const runBox = await panel.getByTestId('run').boundingBox();
        const inputsBox = await panel.getByRole('tab', { name: 'Inputs' }).boundingBox();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        check('7 on a phone Run is above the inputs and nothing scrolls sideways', !!runBox && !!inputsBox && runBox.y < inputsBox.y && !overflow, { runY: runBox?.y, inputsY: inputsBox?.y, overflow });
        await page.setViewportSize({ width: 1440, height: 1000 });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: 'core' } },
);

finish();
