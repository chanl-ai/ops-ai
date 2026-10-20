// uc-106 lists tab once per row, mock-backed pages say Preview, versioned settings save from the button, ui layer:
// docs/usecases/console/lists-preview-and-versioned-saves.md. Signed in through platform-service.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const PREFIX = `uc106-${TAG}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@northfieldbank.com';
const MAYA = 'm.okafor@northfieldbank.com';
const SAM = 's.adeyemi@northfieldbank.com';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;

const signIn = async (browser, consoleUrl, email) => {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => (page.errors ??= []).push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    for (let i = 0; i < 25; i++) {
      const made = await fetch(`${agents}/v1/guardrails`, { method: 'POST', headers: J, body: JSON.stringify({ name: `${PREFIX}-${String(i).padStart(2, '0')}`, topics: ['stock tips'], message: 'I cannot give stock tips.' }) });
      if (!made.ok) throw new Error(`setup: creating guardrail ${i} answered ${made.status}: ${await made.text()}`);
    }

    const skill = await (await fetch(`${agents}/v1/skills`, { method: 'POST', headers: J, body: JSON.stringify({ name: `${PREFIX} skill`, use_when: 'A person asks about opening hours', instructions: 'Answer from the branch hours page.', owner_team: 'team_ops' }) })).json();
    if (!skill.data) throw new Error(`setup: creating the skill: ${JSON.stringify(skill).slice(0, 300)}`);

    const browser = await chromium.launch();
    try {
      // Steps 1-2: a reviewer reads a 25-row list.
      const maya = await signIn(browser, consoleUrl, MAYA);
      await maya.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const search = maya.getByPlaceholder(/^Search/).first();
      await search.fill(PREFIX, { timeout: 120_000 });
      await maya.getByRole('combobox').filter({ hasText: /^10$/ }).click();
      await maya.getByRole('option', { name: '30', exact: true }).click();
      const rows = maya.locator('tbody tr');
      await maya.waitForFunction((n) => document.querySelectorAll('tbody tr').length === n, 25, { timeout: 30_000 }).catch(() => undefined);
      const shape = await maya.evaluate(() => {
        const trs = [...document.querySelectorAll('tbody tr')];
        return { rows: trs.length, tabindex: trs.filter((r) => r.hasAttribute('tabindex')).length, oneLink: trs.filter((r) => r.querySelectorAll('a[href]').length === 1).length };
      });
      check('25 rows, none a tab stop, each holding one link to its record', shape.rows === 25 && shape.tabindex === 0 && shape.oneLink === 25, shape);

      // Counted from the first row, so a filter added to the toolbar does not move the bar.
      await maya.locator('tbody tr a[href]').first().focus();
      let inTable = 1;
      let after = 0;
      let reached = false;
      for (let i = 0; i < 80 && !reached; i++) {
        await maya.keyboard.press('Tab');
        reached = await maya.evaluate(() => {
          const a = document.activeElement;
          const text = (a?.textContent ?? '').trim();
          return !!a && (/Go to (first|previous|next|last) page/.test(text) || (/^(10|20|30|50|100)$/.test(text) && !!a.closest('div')?.parentElement?.textContent?.includes('Rows per page')));
        });
        if (reached) break;
        if (await maya.evaluate(() => !!document.activeElement?.closest('tbody'))) inTable++;
        else after++;
      }
      // Each row is three stops since c-181 (rule 4): its select checkbox, its copy-id button, its record link. Counting starts
      // at the first row's link, so that row's checkbox and copy button (which come before it) are not in the count.
      check('three Tab stops per row (select, copy id, link): 73 inside the table', inTable === 25 * 3 - 2, { inTable });
      check('at most 3 stops between the last row and the pagination', reached && after <= 3, { after, reached });

      // Step 2b: lists whose rows navigate hold a link to the record, so a row opens in a new tab and Tab stops once.
      const lists = [
        ['/tools', '/tools/'],
        ['/widgets', '/widgets/'],
        ['/integrations', '/integrations/'],
      ];
      const linked = {};
      for (const [path, prefix] of lists) {
        await maya.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const first = maya.locator('tbody tr').first();
        await first.waitFor({ timeout: 120_000 }).catch(() => undefined);
        linked[path] = await first.evaluate((tr, pre) => !tr.hasAttribute('tabindex') && [...tr.querySelectorAll('a[href]')].some((a) => (a.getAttribute('href') ?? '').startsWith(pre)), prefix).catch(() => false);
      }
      check('rows of tools, widgets and connections hold a link to their record', Object.values(linked).every(Boolean), linked);

      // Step 2c: a list with no match draws its empty state inside a 400 px viewport, not in a cell of the scrolling table.
      await maya.setViewportSize({ width: 400, height: 900 });
      await maya.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByPlaceholder(/^Search/).first().fill(`${PREFIX}-no-such-guardrail`, { timeout: 120_000 });
      const emptyBox = await maya.getByTestId('table-empty').boundingBox({ timeout: 30_000 }).catch(() => null);
      const clear = await maya.getByTestId('table-empty').getByRole('button').first().boundingBox().catch(() => null);
      check('at 400 px an empty list shows its message and button inside the viewport', !!emptyBox && !!clear && emptyBox.x >= 0 && emptyBox.x + emptyBox.width <= 400 && clear.x >= 0 && clear.x + clear.width <= 400, { emptyBox, clear });
      await maya.setViewportSize({ width: 1440, height: 1000 });

      // Step 2d: the skill's add-tool control is named by the text a person reads on it.
      const james = await signIn(browser, consoleUrl, JAMES);
      await james.goto(`${consoleUrl}/skills/${skill.data.id}?tab=instructions`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const addTool = await james.getByRole('button', { name: 'Add a tool operation' }).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('the skill add-tool menu is named by its visible text', addTool);

      // Steps 3-4: Sam changes Storage; Enter saves nothing, the button saves a version.
      const sam = await signIn(browser, consoleUrl, SAM);
      const puts = [];
      sam.on('request', (r) => r.method() !== 'GET' && /storage|settings/.test(r.url()) && puts.push(`${r.method()} ${new URL(r.url()).pathname}`));
      await sam.goto(`${consoleUrl}/settings/storage`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const minutes = sam.getByLabel('Signed link lifetime');
      const was = await minutes.inputValue({ timeout: 120_000 });
      const next = was === '7' ? '8' : '7';
      await minutes.fill(next);
      await minutes.press('Enter');
      await sam.waitForTimeout(1500);
      check('Enter in a storage field saves no version', puts.length === 0 && !(await sam.getByText(/Saved as version/).first().isVisible().catch(() => false)), puts);
      await sam.getByTestId('storage-save').click();
      const saved = await sam.getByText(/Saved as version/).first().waitFor({ timeout: 15_000 }).then(() => true, () => false);
      check('the Save button saves a new version', saved, puts);

      // Steps 5-6: a page no service serves says Preview; one a service serves does not.
      // Webhooks have no service yet; Members and Access are platform-service's since c-077.
      await sam.goto(`${consoleUrl}/settings/webhooks`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const header = sam.getByTestId('page-header');
      await header.waitFor({ timeout: 120_000 });
      const badge = await header.getByTestId('preview-badge').waitFor({ timeout: 15_000 }).then(() => true, () => false);
      // Settings has its own sidebar, so the app sidebar's rows are read from a page outside it.
      await sam.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
      await sam.waitForTimeout(500);
      const navBadges = await sam.locator('[data-sidebar="menu-button"]').filter({ has: sam.getByTestId('preview-badge') }).allInnerTexts();
      check('a mock-backed page shows Preview in its header and Settings shows it in the sidebar, Files and Access do not', badge && ['Settings'].every((n) => navBadges.some((t) => t.includes(n))) && !navBadges.some((t) => t.includes('Access') || t.includes('Files')), navBadges);
      // The badge follows which service URLs are set: Wiki has none, Guardrails is on agents-service.
      const previewOn = async (path) => {
        await sam.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
        await sam.waitForTimeout(500);
        return (await sam.getByTestId('page-header').getByTestId('preview-badge').count()) > 0;
      };
      const marks = { wiki: await previewOn('/wiki'), modelRisk: await previewOn('/model-risk'), guardrails: await previewOn('/guardrails') };
      check('Wiki and Model inventory show Preview, Guardrails does not', marks.wiki && marks.modelRisk && !marks.guardrails, marks);
      await sam.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('egress-hosts').waitFor({ timeout: 120_000 });
      check('a page a service serves shows no Preview', (await sam.getByTestId('page-header').getByTestId('preview-badge').count()) === 0);

      const errors = [...(maya.errors ?? []), ...(sam.errors ?? [])];
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true } },
);

finish();
