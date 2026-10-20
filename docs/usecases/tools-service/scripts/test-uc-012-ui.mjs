// uc-012 a builder imports tools from OpenAPI, ui layer: docs/usecases/tools-service/import-tools.md. Headless Chromium
// against a console whose Tools pages call tools-service, which reads the fake bank's document at https://api.bank.test.
import { TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const JSONH = { 'Content-Type': 'application/json' };
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const post = (path, body) => fetch(`${tools}${path}`, { method: 'POST', headers: JSONH, body: JSON.stringify(body) });

await withUiStack(
  async (consoleUrl, { bank }) => {
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const specUrl = `https://${bank.host}/v1/openapi.json`;
      // The admin lists the bank on the Egress page: its host, then the private range it resolves into.
      const addEntry = async (button, value, note) => {
        await page.getByRole('button', { name: button }).click();
        const d = page.getByRole('dialog', { name: /^Add a / });
        await d.getByLabel(/^(Host|Range)$/).fill(value);
        await d.getByLabel('Note').fill(note);
        const res = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().startsWith(`${tools}/v1/egress/`), { timeout: 60_000 }));
        await d.getByTestId('egress-add-submit').click();
        return { res: await res, dialog: d };
      };
      await page.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'Add host' }).waitFor({ timeout: 120_000 });
      const host = await addEntry('Add host', bank.host, 'uc-012 fake bank');
      const range = await addEntry('Add range', bank.range, 'uc-012 fake bank network');
      const hostsTable = page.getByTestId('egress-hosts');
      const rangesTable = page.getByTestId('egress-ranges');
      const listed = await Promise.all([hostsTable.getByText(bank.host, { exact: true }).waitFor({ timeout: 30_000 }), rangesTable.getByText(bank.range, { exact: true }).waitFor({ timeout: 30_000 })]).then(() => true, () => false);
      check('the Egress page lists the bank host and its private range', host.res?.status() === 201 && range.res?.status() === 201 && listed, { host: host.res?.status(), range: range.res?.status(), hosts: await hostsTable.innerText(), ranges: await rangesTable.innerText() });
      const loopback = await addEntry('Add range', '127.0.0.0/8', 'should be refused');
      const reason = await loopback.dialog.locator('#egress-value').locator('xpath=following-sibling::p').innerText().catch(() => '');
      check('a range that may never be listed is refused (400) and the dialog shows why', loopback.res?.status() === 400 && reason.length > 10 && reason.includes('127'), { status: loopback.res?.status(), reason });
      await page.keyboard.press('Escape');

      await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'Import operations' }).first().click({ timeout: 120_000 });
      const dialog = page.getByRole('dialog', { name: 'Import operations' });
      await dialog.locator('#mk-openapi').click();
      await dialog.getByLabel('Spec URL').fill(specUrl);
      const discovered = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${tools}/v1/tool-modules/discover`, { timeout: 60_000 }));
      await dialog.getByTestId('import-next').click();
      const discoverRes = await discovered;
      const found = discoverRes ? (await discoverRes.json()).data : undefined;
      // Access comes from the method (c-048 T006): both documented operations are GETs, so both read and start selected.
      check('the dialog reads the bank document through tools-service, each GET a read', discoverRes?.status() === 200 && found?.operations?.every((o) => o.access === 'read') && found.operations.length === 2, { status: discoverRes?.status(), ops: found?.operations?.map((o) => [o.name, o.access]) });

      await dialog.locator('#op-latest_statement').click();
      const created = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${tools}/v1/tool-modules`, { timeout: 60_000 }));
      await dialog.getByTestId('import-save').click();
      const createRes = await created;
      const sent = createRes ? JSON.parse(createRes.request().postData() ?? '{}') : {};
      const module = createRes ? (await createRes.json()).data : undefined;
      check('create sends the source the operations came from', sent.source?.kind === 'openapi' && sent.source?.specUrl === specUrl && sent.operations?.map((o) => o.name).join() === 'get_account', { source: sent.source, ops: sent.operations?.map((o) => o.name) });
      const op = module?.operations?.[0];
      check('the saved operation takes its method and path from the document', createRes?.status() === 201 && op?.name === 'get_account' && op?.method === 'GET' && op?.path === '/accounts/{accountId}', { status: createRes?.status(), op: op && [op.name, op.method, op.path] });
      const opened = await page.waitForURL(`**/tools/${module?.id}`, { timeout: 60_000 }).then(() => true, () => false);
      check('the new module opens on its page', opened, page.url());

      // Non-vacuous half: a caller-written method and path for a documented operation is replaced by the document's.
      // Tool names are unique across modules, so the module made above goes first.
      await fetch(`${tools}/v1/tool-modules/${module?.id}`, { method: 'DELETE' });
      const forged = await post('/v1/tool-modules', { name: 'uc012-ui-forged', displayName: 'Forged', system: 'Forged', type: 'openapi', endpoint: found.endpoint, connectionId: 'int_core_banking', source: { kind: 'openapi', specUrl }, operations: [{ ...found.operations.find((o) => o.name === 'get_account'), method: 'DELETE', path: '/admin' }] });
      const forgedModule = forged.ok ? (await forged.json()).data : undefined;
      const forgedOp = forgedModule?.operations?.[0];
      check('a forged method and path are replaced by the document', forgedOp?.method === 'GET' && forgedOp?.path === '/accounts/{accountId}', { status: forged.status, op: forgedOp && [forgedOp.method, forgedOp.path], body: forged.ok ? undefined : (await forged.text()).slice(0, 200) });

      // The forged module calls the bank host, so removing the host is refused (409) and the toast names that module.
      await page.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const hostRow = page.getByTestId('egress-hosts').getByRole('row', { name: new RegExp(bank.host.replace(/\./g, '\\.')) });
      await hostRow.waitFor({ timeout: 60_000 });
      check('the host links the module that calls it', (await hostRow.getByRole('link', { name: forgedModule?.id }).count()) === 1, { row: await hostRow.innerText(), forged: forgedModule?.id });
      await hostRow.getByRole('button').last().click();
      await page.getByRole('menuitem', { name: 'Remove' }).click();
      const removed = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${tools}/v1/egress/hosts/remove`, { timeout: 60_000 }));
      await page.getByRole('dialog', { name: /^Remove host/ }).getByRole('button', { name: 'Remove', exact: true }).click();
      const removeRes = await removed;
      const toastText = await page.locator('[data-sonner-toast]').filter({ hasText: 'Couldn’t remove' }).first().innerText({ timeout: 10_000 }).catch(() => '');
      check('a host a module calls cannot be removed (409), and the refusal names the module', removeRes?.status() === 409 && !!forgedModule && toastText.includes(forgedModule.id), { status: removeRes?.status(), toastText });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { tools: { bank: true } },
);

finish();
