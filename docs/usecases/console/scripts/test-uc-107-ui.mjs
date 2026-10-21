// uc-107 a Security admin manages every secret in one place, ui layer: docs/usecases/console/secrets-in-one-place.md.
// Signed in through platform-service as the seeded people. A published module whose two operations read one secret
// from the fake core bank's query-key route is set up through the API; the secret starts with a wrong value, so a live
// run fails until the rotation. Each step is checked on its own.
import { PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const KEY = `STMT_KEY_${TAG.toUpperCase()}`;
const OPS = [`get_statement_${TAG}`, `get_statement_copy_${TAG}`];
// Three more read the same key, so the Used by cell has five and must cap its chips at three.
const MORE = [`get_statement_a_${TAG}`, `get_statement_b_${TAG}`, `get_statement_c_${TAG}`];
const ACCOUNT = 'CHQ-2219';
// The fake bank's key (FAKE_BANK_KEY's default); the secret holds a wrong one until Sam rotates it.
const BANK_KEY = 'dev-bank-key';
const JAMES = 'j.richardson@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
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
  async (consoleUrl, stack) => {
    const S = await as(SAM, 'team_security');
    const J = await as(JAMES, 'team_ops');
    const N = await as('n.petrov@harborpine.example', 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.bank.host, note: 'uc-107' }) });
    await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.bank.range, note: 'uc-107' }) });
    await json(await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: KEY, value: 'not-the-key' }) }));
    const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Statements ${TAG}`, name: `uc107-stmt-${TAG}`, type: 'http' }) }))).id;
    for (const name of [...OPS, ...MORE]) {
      await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name, description: 'The latest statement', access: 'read', method: 'GET', url: `https://${stack.bank.host}/accounts/{account_id}/statement?api_key={{${KEY}}}`, headers: [] }) }));
    }
    await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-107' }) }));
    await approveToolReview(id, N);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const sam = await signIn(browser, consoleUrl, SAM, errors);
      const james = await signIn(browser, consoleUrl, JAMES, errors);
      const secretsPage = async () => {
        await sam.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        // The search is the server's; its answer re-renders the rows, which would close a row menu opened before it.
        const searched = armed(sam.waitForResponse((r) => r.url().includes(`/v1/secrets?`) && r.url().includes(`search=${KEY}`), { timeout: 60_000 }));
        await sam.getByPlaceholder('Search secrets…').fill(KEY);
        await searched;
        const row = sam.getByRole('row', { name: new RegExp(KEY) });
        await row.waitFor({ timeout: 120_000 });
        return row;
      };
      const menu = async (row, item) => {
        await row.getByRole('button', { name: 'Open menu' }).click();
        return sam.getByRole('menuitem', { name: item });
      };
      // A live run of one operation from its workbench, as James; the gateway's answer.
      const runLive = async (op) => {
        await james.goto(`${consoleUrl}/tools/${id}/operations/${op}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const panel = james.getByTestId('module-test-panel');
        await panel.waitFor({ timeout: 120_000 });
        await panel.getByRole('radio', { name: 'Test environment' }).or(panel.getByRole('button', { name: 'Test environment' })).first().click();
        await panel.locator('#t-account_id').fill(ACCOUNT);
        const ran = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${id}/test`), { timeout: 60_000 }));
        await panel.getByRole('button', { name: 'Run' }).click();
        const res = await ran;
        const text = res ? await res.text() : '';
        const data = text ? (JSON.parse(text).data ?? {}) : {};
        return { status: data.status, code: data.output?.error?.code, leaked: text.includes(BANK_KEY) };
      };

      // 1. The secret lists both operations that read it, each linked to its workbench; storage credentials are listed too.
      await step('1 the secret lists the operations that read it', async () => {
        const row = await secretsPage();
        const users = sam.getByTestId(`secret-users-${KEY}`);
        const links = await users.getByRole('link').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
        const storage = await sam.getByText('Storage credentials', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        // Five operations read it: three chips, each linked to its workbench, then "and 2 more" naming the rest.
        const more = users.getByTestId(`secret-users-more-${KEY}`);
        const rest = await more.hover().then(() => sam.getByRole('tooltip').first().innerText(), () => '');
        const all = [...OPS, ...MORE];
        check(
          '1 the secret lists three operations and counts the rest',
          links.length === 3 && links.every((h) => all.some((op) => h === `/tools/${id}/operations/${op}`)) && (await more.innerText()) === 'and 2 more' && all.filter((op) => !links.some((h) => h.endsWith(`/${op}`))).every((op) => rest.includes(op)) && storage && (await row.count()) === 1,
          { links, rest, storage },
        );
      });

      // 1b. Storage credentials draw skeleton rows while they load, as Storage does, not a line of text.
      await step('1b storage credentials load as skeleton rows', async () => {
        await sam.route('**/settings/storage/credentials', async (route) => {
          await new Promise((r) => setTimeout(r, 4000));
          await route.fallback();
        });
        await sam.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const skeleton = await sam.getByTestId('storage-credentials-loading').waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const text = await sam.getByText('Loading…', { exact: true }).count();
        await sam.unroute('**/settings/storage/credentials');
        check('1b storage credentials load as skeleton rows', skeleton && text === 0, { skeleton, text });
      });

      // 2. Delete stays off while the operations read it, with them as the reason.
      await step('2 delete is off while operations read it', async () => {
        const row = await secretsPage();
        const del = await menu(row, /Delete/);
        const disabled = (await del.getAttribute('aria-disabled')) === 'true' || (await del.getAttribute('data-disabled')) !== null;
        const reason = await del.innerText();
        await sam.keyboard.press('Escape');
        const api = await fetch(`${tools}/v1/secrets/${KEY}`, { method: 'DELETE', headers: S });
        check('2 delete is off while operations read it', disabled && reason.includes('Read by 5 operations') && api.status === 409, { disabled, reason, api: api.status });
      });

      // 3. With the wrong value both runs fail; after Sam rotates it in the console, both send the new value.
      await step('3 a rotation reaches both operations', async () => {
        const before = await runLive(OPS[0]);
        const row = await secretsPage();
        await (await menu(row, /Rotate/)).click();
        const dialog = sam.getByRole('dialog', { name: `Rotate ${KEY}` });
        await dialog.locator('#secret-value').fill(BANK_KEY);
        const rotated = armed(sam.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/secrets/${KEY}/rotate`), { timeout: 60_000 }));
        await dialog.getByTestId('secret-submit').click();
        const res = await rotated;
        const after = [await runLive(OPS[0]), await runLive(OPS[1])];
        check(
          '3 a rotation reaches both operations',
          before.status === 401 && res?.status() === 200 && after.every((a) => a.status === 200 && !a.leaked),
          { before, rotate: res?.status(), after },
        );
      });

      // 4. Limited to the Security team, the Operations module's runs are refused and its workbench says why.
      await step('4 a team scope refuses another team’s module', async () => {
        const row = await secretsPage();
        await (await menu(row, /Change teams/)).click();
        const dialog = sam.getByRole('dialog', { name: `Teams for ${KEY}` });
        const grouped = (await dialog.getByRole('group', { name: 'Teams' }).getByRole('checkbox', { name: 'Security' }).count()) === 1;
        await dialog.getByRole('checkbox', { name: 'Security' }).click();
        // A failed save stays in the dialog, shown there, and the person fixes it without leaving.
        await sam.route(`**/v1/secrets/${KEY}`, (route) => (route.request().method() === 'PATCH' ? route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'INTERNAL', message: 'The gateway could not save the teams.' } }) }) : route.fallback()));
        await dialog.getByTestId('secret-scope-submit').click();
        const inline = await dialog.getByRole('alert').filter({ hasText: /could not save the teams/ }).waitFor({ timeout: 15_000 }).then(() => true, () => false);
        await sam.unroute(`**/v1/secrets/${KEY}`);
        const saved = armed(sam.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/secrets/${KEY}`), { timeout: 60_000 }));
        await dialog.getByTestId('secret-scope-submit').click();
        const res = await saved;
        const run = await runLive(OPS[0]);
        const said = await james.getByTestId(`secret-out-of-scope-${KEY}`).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check('4 a team scope refuses another team’s module', grouped && inline && res?.status() === 200 && run.code === 'SECRET_OUT_OF_SCOPE' && said, { grouped, inline, scope: res?.status(), run, said });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: 'core' } },
);

finish();
