// uc-580 A team admin connects every system for real, from one dialog, ui layer: docs/usecases/console/connect-every-system.md
// (c-580). The ui stack with the console switch NEXT_PUBLIC_OPS_REAL_CONNECTIONS on: Connections is a grid of the team's
// systems read from tools-service's GET /v1/systems through the generated SDK, with search, a category filter and
// another team's system kept out. Last, a stack with the switch off, the default, shows the shipped page and never asks
// for the systems. Screenshots go to evidenceDir('580', 'uc').
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

import { allowBank } from '../../lib/connection_ui.mjs';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('580', 'uc');
const TAG = Math.random().toString(36).slice(2, 6);
const SWITCH = { NEXT_PUBLIC_OPS_REAL_CONNECTIONS: '1' };
// The bank stand-in's keys (services/tools-service/scripts/fake_bank/bank_auth.py, GET /auth/api-key).
const BANK_KEY = 'test-bank-key';
const WRONG_KEY = 'not-the-bank-key';

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const call = async (method, path, headers, body) => {
  const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const json = await r.json().catch(() => ({}));
  return { status: r.status, data: json.data, error: json.error };
};
const systems = async (headers) => (await call('GET', '/v1/systems', headers)).data ?? [];
const signIn = async (browser, consoleUrl, email, width = 1280) => {
  const page = await (await browser.newContext({ viewport: { width, height: 900 } })).newPage();
  page.errors = [];
  page.systemsCalls = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  page.on('request', (r) => {
    if (new URL(r.url()).pathname === '/v1/systems') page.systemsCalls.push({ url: r.url(), auth: Boolean(r.headers().authorization), team: r.headers()['x-team-id'] });
  });
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};

await withUiStack(
  async (consoleUrl, stack) => {
    mkdirSync(SHOTS, { recursive: true });
    await allowBank(stack.bank);
    const bank = `https://${stack.bank.host}`;
    const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
    const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
    const claims = await call('POST', '/v1/connections', priya, { name: `Claims core ${TAG}`, authKind: 'api_key', category: 'Core insurance', description: 'Policies and claims.' });
    const ledger = await call('POST', '/v1/connections', priya, { name: `Ledger ${TAG}`, authKind: 'bearer', category: 'Finance' });
    const vault = await call('POST', '/v1/connections', sam, { name: `Vault ${TAG}`, authKind: 'bearer', category: 'Finance' });
    check('0 set-up: two connections for Operations and one for Security', [claims, ledger, vault].every((r) => r.status === 201), { statuses: [claims, ledger, vault].map((r) => r.status) });

    const browser = await chromium.launch();
    try {
      const page = await signIn(browser, consoleUrl, 'p.shah@harborpine.example');
      await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const grid = page.getByTestId('systems-grid');
      await grid.waitFor({ timeout: 60_000 });
      const claimsCard = page.getByTestId(`system-${claims.data.id}`);
      const ledgerCard = page.getByTestId(`system-${ledger.data.id}`);
      const claimsText = (await claimsCard.textContent()) ?? '';
      const envs = await claimsCard.locator('[data-testid^=system-]').count();
      check(
        "1 the grid shows the team's connections as cards, each with its category, line and both environments",
        claimsText.includes(`Claims core ${TAG}`) && claimsText.includes('Core insurance') && claimsText.includes('Policies and claims.') && (await ledgerCard.count()) === 1 && envs === 2,
        { claimsText: claimsText.slice(0, 200), envs },
      );
      const body = (await page.locator('body').textContent()) ?? '';
      check('1b the grid is not marked Preview or sample data', !/sample data/i.test(body), { body: body.slice(0, 300) });
      await page.screenshot({ path: join(SHOTS, 'grid-1280.png'), fullPage: true });

      const calls = page.systemsCalls;
      check('2 the grid reads GET /v1/systems from tools-service with the session token and the team', calls.length > 0 && calls.every((c) => c.url.startsWith(tools) && c.auth && c.team === 'team_ops'), { calls });

      const vaultShown = await page.getByTestId(`system-${vault.data.id}`).count();
      check("3 another team's connection never reaches this team's grid", vaultShown === 0, { vaultShown });

      await page.getByLabel('Search systems').fill(`ledger ${TAG}`);
      const searched = [await claimsCard.count(), await ledgerCard.count()];
      await page.getByLabel('Search systems').fill('');
      await page.getByLabel('Category').click();
      await page.getByRole('option', { name: 'Core insurance' }).click();
      const filtered = [await claimsCard.count(), await ledgerCard.count()];
      check('4 search and the category filter narrow the grid', searched.join() === '0,1' && filtered.join() === '1,0', { searched, filtered });

      const small = await signIn(browser, consoleUrl, 'p.shah@harborpine.example', 375);
      await small.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await small.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
      const overflow = await small.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      await small.screenshot({ path: join(SHOTS, 'grid-375.png'), fullPage: true });
      check('5 at 375 px the grid fits with no sideways scroll', overflow <= 0, { overflow });

      // The connect dialog: a new system by name, its key refused then working, on the bank stand-in.
      const dialog = page.getByTestId('connect-dialog');
      const testSection = dialog.getByTestId('env-test');
      const fillTest = async ({ baseUrl, key, testPath }) => {
        await testSection.locator('#test-baseUrl').fill(baseUrl);
        if (testPath) {
          if (!(await testSection.locator('#test-testPath').isVisible())) await testSection.getByRole('button', { name: 'More settings' }).click();
          await testSection.locator('#test-testPath').fill(testPath);
        }
        await testSection.locator('#test-key').fill(key);
      };
      const pressTest = async () => {
        const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 });
        await testSection.getByTestId('test-test').click();
        await answered;
        // The section's result is replaced when the test's answer is applied, which frees its Test button again.
        await page.waitForFunction(() => document.querySelector('[data-testid="env-test"] [data-testid="test-test"]')?.disabled === false, null, { timeout: 30_000 });
        const health = testSection.getByTestId('health-test');
        await health.waitFor({ timeout: 30_000 });
        const error = (await dialog.getByTestId('connect-error').count()) ? await dialog.getByTestId('connect-error').innerText() : null;
        return { status: await health.getAttribute('data-status'), said: ((await health.innerText()) ?? '').replace(/\s+/g, ' '), error };
      };
      await page.getByLabel('Search systems').fill('');
      await page.getByLabel('Category').click();
      await page.getByRole('option', { name: 'Every category' }).click();
      await page.getByTestId('connect-system').click();
      await dialog.waitFor({ timeout: 30_000 });
      await dialog.getByLabel('System name').fill(`Bank API ${TAG}`);
      await fillTest({ baseUrl: bank, key: WRONG_KEY, testPath: '/auth/api-key' });
      const refused = await pressTest();
      check("8 a new system's wrong key tests Failed with the system's 401", refused.status !== 'ok' && /Failed/.test(refused.said) && /\b401\b/.test(refused.said), refused);
      await testSection.locator('#test-key').fill(BANK_KEY);
      const working = await pressTest();
      check('9 the right key, typed over it, tests Working with 200', working.status === 'ok' && /\b200\b/.test(working.said), working);
      const sealed = await testSection.locator('#test-key').getAttribute('placeholder');
      const shown = ((await dialog.innerText()) ?? '').includes(BANK_KEY) || (await testSection.locator('#test-key').inputValue()) !== '';
      await page.screenshot({ path: join(SHOTS, 'dialog-1280.png'), fullPage: true });
      await dialog.getByTestId('connect-submit').click();
      await dialog.waitFor({ state: 'detached', timeout: 30_000 });
      const listed = (await systems(priya)).find((c) => c.name === `Bank API ${TAG}`);
      check('10 Save keeps it: one card, test set and working; the key reads Sealed and never shows', Boolean(listed) && listed.environments.test.set && listed.environments.test.health?.status === 'ok' && /Sealed/.test(sealed ?? '') && !shown, { listed, sealed, shown });

      // The connection's page: each environment's last test, and Edit keys opening the dialog on that environment with
      // the key sealed. A changed key's test reads the new key.
      await page.goto(`${consoleUrl}/tools/connections/${listed?.connectionId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const envRow = page.getByTestId('health-test');
      await envRow.waitFor({ timeout: 60_000 });
      const rowSaid = await envRow.getAttribute('data-status');
      await page.getByTestId('edit-test').click();
      await dialog.waitFor({ timeout: 30_000 });
      const sealedAgain = await testSection.locator('#test-key').getAttribute('placeholder');
      await testSection.locator('#test-key').fill(WRONG_KEY);
      const changed = await pressTest();
      await testSection.locator('#test-key').fill(BANK_KEY);
      const back = await pressTest();
      await dialog.getByTestId('connect-submit').click();
      await dialog.waitFor({ state: 'detached', timeout: 30_000 });
      await page.waitForFunction(() => document.querySelector('[data-testid="health-test"]')?.getAttribute('data-status') === 'ok', null, { timeout: 30_000 }).catch(() => {});
      const pageSaid = await page.getByTestId('health-test').getAttribute('data-status');
      check(
        "14 Edit keys on the page opens the dialog sealed; a changed key's test reads it (401), the right one again 200, and the page shows Working",
        rowSaid === 'ok' && /Sealed/.test(sealedAgain ?? '') && /\b401\b/.test(changed.said) && back.status === 'ok' && pageSaid === 'ok',
        { rowSaid, sealedAgain, changed, back, pageSaid },
      );
      await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('systems-grid').waitFor({ timeout: 60_000 });

      // A system whose test address answers 404, cancelled: the connection the first Test made is deleted.
      await page.getByTestId('connect-system').click();
      await dialog.waitFor({ timeout: 30_000 });
      await dialog.getByLabel('System name').fill(`Nowhere ${TAG}`);
      await fillTest({ baseUrl: bank, key: BANK_KEY, testPath: '/no-such-page' });
      const missing = await pressTest();
      await dialog.getByTestId('connect-cancel').click();
      await dialog.waitFor({ state: 'detached', timeout: 30_000 });
      const left = (await systems(priya)).filter((c) => c.name === `Nowhere ${TAG}`);
      check('11 a test answering 404 says Failed 404, and Cancel deletes the system the test made', missing.status !== 'ok' && /\b404\b/.test(missing.said) && left.length === 0, { missing, left });

      // A tool module with no connection: connected from its card, it becomes part of one connection card.
      const mod = await call('POST', '/v1/tool-modules', priya, { name: `uc580-accounts-${TAG}`, displayName: `Accounts ${TAG}`, system: 'Bank', type: 'http', endpoint: '', http: { name: `uc580_accounts_${TAG}`, description: 'Read an account', access: 'read', method: 'GET', url: `${bank}/auth/api-key` } });
      await page.reload({ waitUntil: 'domcontentloaded' });
      const modCard = page.getByTestId(`system-module:${mod.data?.id}`);
      await modCard.waitFor({ timeout: 60_000 });
      await page.getByTestId(`connect-module:${mod.data?.id}`).click();
      await dialog.waitFor({ timeout: 30_000 });
      await fillTest({ baseUrl: bank, key: BANK_KEY, testPath: '/auth/api-key' });
      const modTest = await pressTest();
      await dialog.getByTestId('connect-submit').click();
      await dialog.waitFor({ state: 'detached', timeout: 30_000 });
      const holding = (await systems(priya)).filter((c) => c.moduleIds.includes(mod.data?.id));
      await page.getByTestId('systems-grid').waitFor();
      const moduleCardLeft = await modCard.count();
      check('12 a module card connected from its card is one connection card, with no module card left', mod.status === 201 && modTest.status === 'ok' && holding.length === 1 && holding[0].kind === 'connection' && moduleCardLeft === 0, { mod: mod.status, modTest, holding: holding.map((c) => [c.kind, c.name]), moduleCardLeft });

      const phone = await signIn(browser, consoleUrl, 'p.shah@harborpine.example', 375);
      await phone.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await phone.getByTestId('connect-system').click();
      const phoneDialog = phone.getByTestId('connect-dialog');
      await phoneDialog.waitFor({ timeout: 30_000 });
      await phone.waitForTimeout(400);
      const sideways = await phoneDialog.evaluate((el) => el.scrollWidth - el.clientWidth);
      await phone.screenshot({ path: join(SHOTS, 'dialog-375.png') });
      check('13 at 375 px the dialog fits with no sideways scroll', sideways <= 0, { sideways });

      // The team's sending policy, written in Govern › Policies right after Check before sending.
      const POLICY = `Never promise a refund in a reply (${TAG}).`;
      await page.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const policyCard = page.getByTestId('setting-send-policy');
      await policyCard.waitFor({ timeout: 60_000 });
      const afterSwitch = await page.evaluate(() => {
        const cards = [...document.querySelectorAll('[data-testid^="setting-"]')].map((e) => e.getAttribute('data-testid'));
        return cards.indexOf('setting-send-policy') === cards.indexOf('setting-policy-checkBeforeSend') + 1;
      });
      await policyCard.getByLabel('Sending policy').fill(POLICY);
      const savedPolicy = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/v1/send-policy'), { timeout: 30_000 });
      await policyCard.getByRole('button', { name: /save/i }).click();
      const policyStatus = (await savedPolicy).status();
      await policyCard.getByText(/Version \d+, saved by Priya Shah/).waitFor({ timeout: 30_000 });
      const stored = (await call('GET', '/v1/send-policy', priya)).data;
      check(
        '18 Priya writes the sending policy right after Check before sending; it saves as a new version with her name',
        afterSwitch && policyStatus === 200 && stored?.text === POLICY && stored?.savedBy === 'Priya Shah' && stored?.version >= 1,
        { afterSwitch, policyStatus, stored },
      );

      // An operation's mock answers: a default that says the bank is down, added on the operation's page.
      const op = (mod.data?.operations ?? [])[0] ?? {};
      await page.goto(`${consoleUrl}/tools/${mod.data?.id}/operations/${encodeURIComponent(op.name)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('mock-add').click();
      const mockDialog = page.getByTestId('mock-dialog');
      await mockDialog.waitFor({ timeout: 30_000 });
      await mockDialog.getByLabel('Name').fill('Bank down');
      await mockDialog.getByLabel('Status').fill('503');
      await mockDialog.getByLabel(/^Body/).fill('{"error": "down"}');
      await mockDialog.getByLabel('Default').click();
      await mockDialog.getByTestId('mock-save').click();
      await mockDialog.waitFor({ state: 'detached', timeout: 30_000 });
      const row = page.getByTestId('mock-answers');
      await row.waitFor({ timeout: 30_000 });
      const rowText = ((await row.innerText()) ?? '').replace(/\s+/g, ' ');
      const ran = await call('POST', `/v1/tool-modules/${mod.data?.id}/test`, priya, { operation: op.name, contextId: 'owner', target: 'stub', input: {} });
      check(
        "19 a mock answer added on the operation's page is listed in order, and a run against the mock gets it: 503 with its body",
        /Bank down/.test(rowText) && /Default/.test(rowText) && /Answers 503/.test(rowText) && ran.data?.status === 503 && JSON.stringify(ran.data?.output ?? ran.data?.rawResponse).includes('down'),
        { rowText, ran: { status: ran.status, error: ran.error, result: ran.data?.status, mockId: ran.data?.mockId, output: ran.data?.output } },
      );

      check('6 no page errors', page.errors.length === 0 && small.errors.length === 0 && phone.errors.length === 0, { errors: [...page.errors, ...small.errors, ...phone.errors] });
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: 'core' }, consoleSwitches: SWITCH },
);

// With the switch off, the default: the shipped Connections page, and the console never asks for the systems.
await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await signIn(browser, consoleUrl, 'p.shah@harborpine.example');
      await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('guided-connect').waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2000);
      const grid = await page.getByTestId('systems-grid').count();
      check('7 off by default: the shipped page shows and GET /v1/systems is never called', grid === 0 && page.systemsCalls.length === 0, { grid, calls: page.systemsCalls });
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

// A plugin from its card: the c-588 test plugin that sends a key in its own header (X-Desk-Key), against the fake
// system of docs/usecases/lib/fake_multi_auth.py. The dialog asks for the key only, never the header it is sent in.
const HEADER_KEY = join(ROOT, 'services/tools-service/tests/plugin_kinds/kinds_header_key');
const fakeProc = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_multi_auth.py')], {
  stdio: ['pipe', 'pipe', 'inherit'],
  env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
});
const fake = JSON.parse(
  await new Promise((resolve, reject) => {
    createInterface({ input: fakeProc.stdout }).once('line', resolve);
    fakeProc.once('exit', (code) => reject(new Error(`fake system exited with ${code}`)));
  }),
);
try {
  await withUiStack(
    async (consoleUrl) => {
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
      const installed = await fetch(`${platform}/v1/policies/plugins`, { method: 'PUT', headers: sam, body: JSON.stringify({ value: { 'test.header-key': { enabled: true } } }) });
      for (const host of fake.hosts) await call('POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-580' });
      await call('POST', '/v1/egress/ranges', sam, { value: fake.range, note: 'uc-580' });
      const browser = await chromium.launch();
      try {
        const page = await signIn(browser, consoleUrl, 'p.shah@harborpine.example');
        await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const card = page.getByTestId('system-plugin:test.header-key');
        for (let i = 0; i < 20 && !(await card.count()); i++) await page.waitForTimeout(1000), await page.reload({ waitUntil: 'domcontentloaded' });
        await card.waitFor({ timeout: 60_000 });
        await page.getByTestId('connect-plugin:test.header-key').click();
        const dialog = page.getByTestId('connect-dialog');
        await dialog.waitFor({ timeout: 30_000 });
        const section = dialog.getByTestId('env-test');
        await section.locator('#test-key').waitFor({ timeout: 30_000 }).catch(() => {});
        const asked = { key: await section.locator('#test-key').count(), name: await section.locator('#test-name').count(), address: await section.locator('#test-baseUrl').count() };
        const pressTest = async () => {
          const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 });
          await section.getByTestId('test-test').click();
          await answered;
          await page.waitForFunction(() => document.querySelector('[data-testid="env-test"] [data-testid="test-test"]')?.disabled === false, null, { timeout: 30_000 });
          const health = section.getByTestId('health-test');
          return { status: await health.getAttribute('data-status'), said: ((await health.innerText()) ?? '').replace(/\s+/g, ' ') };
        };
        await section.locator('#test-key').fill('not-the-desk-key');
        const wrong = await pressTest();
        await section.locator('#test-key').fill(fake.secrets.key);
        const right = await pressTest();
        await page.screenshot({ path: join(SHOTS, 'plugin-dialog-1280.png'), fullPage: true });
        await dialog.getByTestId('connect-submit').click();
        await dialog.waitFor({ state: 'detached', timeout: 30_000 });
        const listed = (await systems(priya)).find((c) => c.pluginId === 'test.header-key');
        const shown = ((await page.locator('body').innerText()) ?? '').includes(fake.secrets.key);
        check(
          "15 a plugin's dialog asks for its key only (not the header it fixes); a wrong key tests Failed 401, the right one Working 200, and Save turns it on with the key unseen",
          installed.status === 200 && asked.key === 1 && asked.name === 0 && asked.address === 0 && /\b401\b/.test(wrong.said) && right.status === 'ok' && listed?.plugin?.teamOn && listed?.environments?.test?.health?.status === 'ok' && !shown,
          { installed: installed.status, asked, wrong, right, teamOn: listed?.plugin?.teamOn, test: listed?.environments?.test, shown },
        );
        check('16 no page errors with plugins on', page.errors.length === 0, page.errors);
      } finally {
        await browser.close();
      }
    },
    { platform: true, tools: { env: { ...fake.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify([HEADER_KEY]) } }, consoleSwitches: SWITCH },
  );
} finally {
  fakeProc.stdin.end();
  const exited = new Promise((resolve) => (fakeProc.exitCode !== null ? resolve() : fakeProc.once('exit', resolve)));
  const timer = setTimeout(() => fakeProc.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
  const left = execFileSync('docker', ['ps', '-q', '--filter', `label=ops.harness.owner=${fake.owner}`], { encoding: 'utf8' }).trim();
  check('17 the run leaves no container of its own behind', left === '', left);
}
finish();
