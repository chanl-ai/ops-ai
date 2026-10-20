// uc-101 a builder builds and debugs a tool operation on its full-width workbench, ui layer:
// docs/usecases/console/tool-workbench.md. Signed in through platform-service as the seeded people. A published module
// with the core bank's statement read (its key in the query string, as the fake's legacy route takes it) is set up
// through the API; everything after is clicked on the workbench. Each step is checked on its own.
import { PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const OP = `get_statement_${TAG}`;
const ACCOUNT = 'CHQ-2219';
// The fake bank's key (FAKE_BANK_KEY's default). It is typed for one run and never set as a tenant secret.
const BANK_KEY = 'dev-bank-key';
const JAMES = 'j.richardson@northfieldbank.com';
const RAVI = 'r.menon@northfieldbank.com';
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
    const SAM = await as('s.adeyemi@northfieldbank.com', 'team_security');
    const J = await as(JAMES, 'team_ops');
    const N = await as('n.petrov@northfieldbank.com', 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: SAM, body: JSON.stringify({ value: stack.bank.host, note: 'uc-101' }) });
    await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: SAM, body: JSON.stringify({ value: stack.bank.range, note: 'uc-101' }) });
    const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Core bank ${TAG}`, name: `uc101-bank-${TAG}`, type: 'http' }) }))).id;
    await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: OP, description: 'The latest statement', access: 'read', method: 'GET', url: `https://${stack.bank.host}/accounts/{account_id}/statement?api_key={{STATEMENTS_API_KEY}}`, headers: [] }) }));
    await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-101' }) }));
    await approveToolReview(id, N);
    const opNow = async () => (await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }))).operations.find((o) => o.name === OP);

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
        await panel.getByRole('button', { name: 'Run' }).click();
        const res = await ran;
        return { res, body: res ? await res.text() : '', data: res ? (JSON.parse((await res.text()) || '{}').data ?? {}) : {} };
      };
      const tab = async (name) => {
        await panel.getByRole('tab', { name }).click();
        return panel.getByRole('tabpanel').innerText();
      };

      // 1. A row of the operations table opens the operation on its own page; the module page has no side console.
      await step('1 the operation opens on its own full-width page', async () => {
        await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByRole('row', { name: new RegExp(OP) });
        await row.waitFor({ timeout: 120_000 });
        // The row is one tab stop: one link to the workbench in its name cell, and no tabindex on the row itself.
        const rowLinks = await row.locator(`a[href$="/operations/${OP}"]`).count();
        const rowTabindex = await row.getAttribute('tabindex');
        const sideConsole = await page.getByTestId('module-test-panel').count();
        await row.click();
        await page.waitForURL(`**/tools/${id}/operations/${OP}`, { timeout: 60_000 });
        const shown = await page.getByTestId('tool-workbench').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const width = shown ? (await page.getByTestId('tool-workbench').boundingBox())?.width ?? 0 : 0;
        check('1 the operation opens on its own full-width page', sideConsole === 0 && shown && width > 900 && rowLinks === 1 && rowTabindex === null, { sideConsole, shown, width, rowLinks, rowTabindex });
      });

      // 2. A draft mock and transform run on the mock without staging; the operation agents call is unchanged.
      await step('2 a draft mock and transform run without changing the operation', async () => {
        await page.locator('#wb-stub').fill(JSON.stringify({ accountId: ACCOUNT, closingBalance: 1520.33, lines: 4 }));
        await page.locator('#wb-transform').fill('{"balance": {{ data.closingBalance }}}');
        await panel.locator(`#t-account_id`).fill(ACCOUNT);
        const { res, data } = await run();
        const output = await tab('Output');
        const raw = await tab('Raw response');
        const op = await opNow();
        const detail = await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }));
        check(
          '2 a draft mock and transform run without changing the operation',
          res?.status() === 200 && /"balance":\s*1520\.33/.test(output) && /closingBalance/.test(raw) && !op.responseTransform && JSON.stringify(op.stub) === '{"ok":true}' && detail.pendingChanges.length === 0,
          { status: res?.status(), output: output.slice(0, 120), raw: raw.slice(0, 120), stub: op.stub, transform: op.responseTransform ?? null, pending: detail.pendingChanges.length, log: data.log?.map((l) => l.message) },
        );
      });

      // 2b. The Run-as list names each context plainly: the owner's has no workflow, so no dangling separator.
      await step('2b the Run-as list has no dangling separator', async () => {
        await panel.locator('#t-ctx').click();
        const options = await page.getByRole('option').allInnerTexts();
        await page.keyboard.press('Escape');
        check('2b the Run-as list has no dangling separator', options.length > 0 && options.some((o) => o.trim() === 'Module owner, no case') && !options.some((o) => o.trim().startsWith('·')), options);
      });

      // 3. A secret value typed for one run reaches the bank; the request shows it masked, and nothing returns it.
      await step('3 a typed secret runs live and shows masked', async () => {
        await page.locator('#wb-transform').fill('');
        await page.getByLabel('STATEMENTS_API_KEY test value').fill(BANK_KEY);
        await panel.getByRole('radio', { name: 'Test environment' }).or(panel.getByRole('button', { name: 'Test environment' })).first().click();
        await panel.locator(`#t-account_id`).fill(ACCOUNT);
        const { res, body, data } = await run();
        const request = await tab('Request');
        const output = await tab('Output');
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
        const input = page.getByLabel('STATEMENTS_API_KEY test value');
        const kept = await input.inputValue();
        const attribute = await input.getAttribute('value');
        const inHtml = await page.evaluate((s) => document.documentElement.outerHTML.includes(s), BANK_KEY);
        check('3b the typed secret is gone from the page once the run ends', kept === '' && !attribute && !inHtml, { kept: kept ? 'still typed' : '', attribute, inHtml });
      });

      // 4. A transform that fails says why under the field and on the result; the output is the raw answer.
      await step('4 a failing transform shows its reason', async () => {
        await panel.getByRole('radio', { name: 'Mock' }).or(panel.getByRole('button', { name: 'Mock' })).first().click();
        await page.locator('#wb-transform').fill('{"b": {{ data.closing.balance }}}');
        await panel.locator(`#t-account_id`).fill(ACCOUNT);
        const { data } = await run();
        const onResult = await panel.getByTestId('test-transform-error').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const underField = await page.locator('#wb-transform').locator('xpath=ancestor::*[@data-slot="form-item" or contains(@class,"flex-col")][1]').innerText().catch(() => '');
        const output = await tab('Output');
        check(
          '4 a failing transform shows its reason',
          !!data.transformError && onResult && underField.includes('closing') && /closingBalance/.test(output),
          { transformError: data.transformError, onResult, underField: underField.slice(0, 160) },
        );
      });

      // 5. The edited mock is staged with the rest and listed as a change to publish.
      await step('5 the edited mock is staged and listed for review', async () => {
        await page.locator('#wb-transform').fill('');
        const staged = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/tool-modules/${id}/operations/`), { timeout: 60_000 }));
        await page.getByTestId('workbench-stage').click();
        const res = await staged;
        const sent = res ? JSON.parse(res.request().postData() ?? '{}') : {};
        const detail = await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }));
        const change = detail.pendingChanges.find((c) => c.operation === OP && c.detail === 'Mock response edited');
        await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const listed = await page.getByText(/unpublished change/).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check('5 the edited mock is staged and listed for review', res?.status() === 200 && sent.stub?.closingBalance === 1520.33 && change?.major === false && listed, { status: res?.status(), sent: sent.stub, change, listed });
      });

      // 6. A viewer opens the same page read-only; a builder never sees the notice, not even while the role loads.
      await step('6 a viewer sees the workbench read-only and a builder never sees View only', async () => {
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
          await p.getByTestId('tool-workbench').waitFor({ timeout: 120_000 });
          return p;
        };
        const ravi = await open(RAVI, false);
        const notice = await ravi.getByTestId('read-only-notice').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const viewer = {
          notice,
          stage: await ravi.getByTestId('workbench-stage').count(),
          policy: await ravi.getByTestId('workbench-policy').count(),
          stubDisabled: await ravi.locator('#wb-stub').isDisabled(),
          secretDisabled: await ravi.getByLabel('STATEMENTS_API_KEY test value').isDisabled(),
        };
        // Below lg Definition and Run are tabs; the fieldset that disables a viewer's fields must not disable the tabs.
        await ravi.setViewportSize({ width: 390, height: 800 });
        const runTab = ravi.getByRole('tab', { name: 'Run' });
        viewer.runTabEnabled = await runTab.isEnabled();
        await runTab.click({ timeout: 5_000 }).catch(() => undefined);
        viewer.runShown = await ravi.getByTestId('module-test-panel').isVisible();
        const james = await open(JAMES, true);
        await james.getByTestId('workbench-stage').waitFor({ timeout: 30_000 });
        await james.waitForTimeout(1500);
        const builder = { stage: await james.getByTestId('workbench-stage').count(), policy: await james.getByTestId('workbench-policy').count(), notice: await james.getByTestId('read-only-notice').count(), flashed: await james.evaluate(() => window.__viewOnly), stubDisabled: await james.locator('#wb-stub').isDisabled() };
        check(
          '6 a viewer sees the workbench read-only and a builder never sees View only',
          viewer.notice && viewer.stage === 0 && viewer.policy === 0 && viewer.stubDisabled && viewer.secretDisabled && viewer.runTabEnabled && viewer.runShown && builder.stage === 1 && builder.policy === 1 && builder.notice === 0 && !builder.flashed && !builder.stubDisabled,
          { viewer, builder },
        );
      });

      // 7. On a phone the definition and the run are tabs, so Run is one tap away instead of below five sections; the wide
      // layout keeps both side by side with no tabs.
      await step('7 on a phone Definition and Run are tabs, and the wide layout has none', async () => {
        await page.goto(`${consoleUrl}/tools/${id}/operations/${OP}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('tool-workbench').waitFor({ timeout: 120_000 });
        await page.locator('#wb-stub').waitFor({ timeout: 60_000 });
        const wideTabs = await page.getByRole('tab', { name: 'Run' }).count();
        const wideBoth = (await page.getByTestId('module-test-panel').isVisible()) && (await page.locator('#wb-stub').isVisible());
        await page.setViewportSize({ width: 390, height: 800 });
        await page.goto(`${consoleUrl}/tools/${id}/operations/${OP}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('tool-workbench').waitFor({ timeout: 120_000 });
        const runTab = page.getByRole('tab', { name: 'Run' });
        const definitionFirst = (await page.getByRole('tab', { name: 'Definition' }).getAttribute('aria-selected')) === 'true' && (await page.locator('#wb-stub').isVisible()) && !(await page.getByTestId('module-test-panel').isVisible());
        await runTab.click();
        const runBox = await panel.getByRole('button', { name: 'Run' }).boundingBox();
        const runShown = await panel.getByRole('button', { name: 'Run' }).isVisible();
        const stubHidden = !(await page.locator('#wb-stub').isVisible());
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        check(
          '7 on a phone Definition and Run are tabs, and the wide layout has none',
          wideTabs === 0 && wideBoth && definitionFirst && runShown && stubHidden && !!runBox && runBox.y < 800 && !overflow,
          { wideTabs, wideBoth, definitionFirst, runShown, stubHidden, runY: runBox?.y, overflow },
        );
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
