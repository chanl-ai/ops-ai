// uc-678 a team takes in SharePoint libraries and Confluence spaces, ui layer:
// docs/usecases/knowledge/sharepoint-and-confluence.md. The SharePoint and Confluence plugins run in
// the stack's tools-service against their fakes (docs/usecases/lib/fake_sharepoint_confluence.py, run as a script), and
// kb-service reads them through it. The team's sign-ins go through the API as the api layer proved them; then James,
// a builder, uses Add source's pickers in the console.  With OPS_USECASE_MEDIA=1 the pictures
// and the clip go to docs/usecases/knowledge/media.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { KB_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, finish, shootBothWidths, videoToGif, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

/** The fakes, started from their script; resolves with what it printed, and a reader of the lines it prints next. */
async function startFakes() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_sharepoint_confluence.py')], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
  });
  const lines = [];
  const waiting = [];
  createInterface({ input: child.stdout }).on('line', (l) => (waiting.length ? waiting.shift()(l) : lines.push(l)));
  const next = () => new Promise((resolve, reject) => {
    if (lines.length) return resolve(lines.shift());
    waiting.push(resolve);
    child.once('exit', (code) => reject(new Error(`the fakes exited with ${code}`)));
  });
  return { child, info: JSON.parse(await next()), next };
}

const fakes = await startFakes();
const plugins = { OPS_PLUGIN_PATHS: JSON.stringify(fakes.info.pluginPaths) };

try {
  await withUiStack(
    async (consoleUrl) => {
      // The team's set-up: Security allows the hosts and range, Priya (team admin) signs both apps in.
      const admin = { Authorization: `Bearer ${await tokenFor('p.shah@harborpine.example')}`, 'X-Team-Id': 'team_ops' };
      const security = { Authorization: `Bearer ${await tokenFor('s.adeyemi@harborpine.example')}`, 'X-Team-Id': 'team_security' };
      fakes.child.stdin.write(`${JSON.stringify({ tools: `http://127.0.0.1:${TOOLS_PORT}`, admin, security })}\n`);
      const done = JSON.parse(await fakes.next());
      check('10a the team signs SharePoint in through Microsoft and Confluence with an API token', done.sharepoint.done === 200 && done.confluence.health?.status === 'ok', done);

      const browser = await chromium.launch();
      const errors = [];
      try {
        const videos = mkdtempSync(join(tmpdir(), 'uc-678-video-'));
        const recording = Date.now();
        const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: videos, size: { width: 1440, height: 900 } } });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(JAMES);
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

        const started = Date.now();
        await page.goto(`${consoleUrl}/data/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'New knowledge base' }).first().click({ timeout: 120_000 });
        await page.getByLabel('Name').fill(`Policies ${TAG}`);
        const made = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/knowledge-bases'), { timeout: 60_000 }));
        await page.getByTestId('kb-create').click();
        const kbId = (await (await made).json()).data.id;
        await page.waitForURL(`**/knowledge/${kbId}**`, { timeout: 60_000 });

        // Steps 10-11: the sites picker searched, Select all, then the picked site's libraries.
        await page.getByTestId('kb-add-source').click({ timeout: 60_000 });
        await page.getByTestId('kb-add-apps').click();
        const add = page.getByTestId('add-source-wizard');
        await add.getByTestId('add-source-kind-files').click({ timeout: 60_000 });
        await add.getByTestId('add-source-next').click();
        await add.getByTestId('add-source-name').fill(`HR libraries ${TAG}`);
        const sites = add.getByTestId('as-sites-picker');
        const libraries = add.getByTestId('as-libraries-picker');
        // Before a search the picker lists every site the connection reads; the search's answer leaves Human Resources.
        await sites.getByTestId('as-sites-option').filter({ hasText: 'Operations' }).waitFor({ timeout: 60_000 });
        await sites.locator('input').fill('human');
        await sites.getByTestId('as-sites-option').filter({ hasText: 'Operations' }).waitFor({ state: 'detached', timeout: 60_000 });
        await sites.getByTestId('as-sites-option').filter({ hasText: 'Human Resources' }).waitFor({ timeout: 60_000 });
        const offered = await sites.getByTestId('as-sites-option').allInnerTexts();
        check('10 the sites picker searched for "human" lists Human Resources only', offered.length === 1 && offered[0].includes('Human Resources'), offered);

        await sites.getByRole('button', { name: 'Select all' }).click();
        await libraries.getByText(/^0 picked · 2 listed/).waitFor({ timeout: 60_000 });
        await libraries.getByRole('button', { name: 'Select all' }).click();
        const libs = await libraries.getByTestId('as-libraries-option').allInnerTexts();
        const sitesCount = await sites.getByText(/^\d+ picked/).innerText();
        const libsCount = await libraries.getByText(/^\d+ picked/).innerText();
        // Picking libraries asks the sites picker again for what they hold; it settles back on the site.
        await sites.getByTestId('as-sites-option').filter({ hasText: 'Human Resources' }).waitFor({ timeout: 60_000 });
        check(
          '11 Select all picks the site, and the libraries picker lists its two libraries, both picked by Select all',
          sitesCount.startsWith('1 picked · 1 listed') && libsCount.startsWith('2 picked · 2 listed') && libs.some((t) => t.includes('Policies Library')) && libs.some((t) => t.includes('Handbook')),
          { sitesCount, libsCount, libs },
        );

        // Step 13: a search nothing matches, then one Graph answers 503 for.
        await sites.locator('input').fill('zebra');
        const none = sites.getByText('No site called “zebra” that this connection can read.');
        await none.waitFor({ timeout: 60_000 });
        check('13a a search nothing matches says no site of that name can be read', await none.isVisible());
        await sites.locator('input').fill(fakes.info.failingQuery);
        const failed = sites.getByText(/Couldn’t list the sites:/);
        await failed.waitFor({ timeout: 60_000 });
        const said = await failed.innerText();
        await page.waitForTimeout(800);
        const clipMs = Date.now() - started;
        check('13b a search Graph refuses says the sites could not be listed, with the reason', said.includes('503'), said);
        await shootBothWidths(page, 'knowledge', 'uc-678-sites-picker-error', async () => page.waitForTimeout(600));
        await page.setViewportSize({ width: 1440, height: 900 });
        await sites.locator('input').fill('');
        await sites.getByTestId('as-sites-option').filter({ hasText: 'Human Resources' }).waitFor({ timeout: 60_000 });

        // Step 12: Create and sync indexes the libraries' files.
        await add.getByTestId('add-source-next').click();
        const creating = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/sources'), { timeout: 60_000 }));
        await add.getByTestId('add-source-create').click({ timeout: 60_000 });
        const created = await creating;
        const source = created ? (await created.json()).data : undefined;
        const picked = created?.request().postDataJSON()?.config?.values;
        const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
        let rows = [];
        for (let i = 0; i < 120 && source; i++) {
          rows = (await (await fetch(`${kb}/v1/sources/${source.id}/items?pageSize=100`, { headers: H })).json()).data?.data ?? [];
          if (rows.length && rows.every((r) => r.status !== 'processing' && r.status !== 'queued')) break;
          await new Promise((r) => setTimeout(r, 500));
        }
        const indexed = rows.filter((r) => r.status === 'indexed').map((r) => r.title).sort();
        check(
          '12 Create and sync makes the source on the site and both libraries, and its first sync indexes their text files',
          created?.status() === 201 && JSON.stringify(picked?.libraries?.slice().sort()) === JSON.stringify([fakes.info.libraries.handbook, fakes.info.libraries.policies].sort()) && picked?.sites?.[0] === fakes.info.sites.hr && indexed.includes('leave.md') && indexed.includes('expenses.txt'),
          { status: created?.status(), values: picked, items: rows.map((r) => [r.title, r.status]) },
        );

        // Step 14: Confluence's spaces picker.
        await page.getByTestId('kb-add-source').click({ timeout: 60_000 });
        await page.getByTestId('kb-add-apps').click();
        await add.getByTestId('add-source-kind-spaces').click({ timeout: 60_000 });
        await add.getByTestId('add-source-next').click();
        const spaces = add.getByTestId('as-spaces-picker');
        await spaces.getByTestId('as-spaces-option').filter({ hasText: 'Legal' }).waitFor({ timeout: 60_000 });
        await spaces.locator('input').fill('eng');
        await spaces.getByTestId('as-spaces-option').filter({ hasText: 'Legal' }).waitFor({ state: 'detached', timeout: 60_000 });
        const spaceRows = await spaces.getByTestId('as-spaces-option').allInnerTexts();
        await shootBothWidths(page, 'knowledge', 'uc-678-spaces-picker', async () => page.waitForTimeout(600));
        check('14 the spaces picker searched for "eng" lists the Engineering space only', spaceRows.length === 1 && spaceRows[0].includes('Engineering'), spaceRows);
        check('no page errors', errors.length === 0, errors);
        await context.close();
        videoToGif(videos, 'knowledge', 'uc-678-pick-libraries', started - recording, clipMs);
        rmSync(videos, { recursive: true, force: true });
      } catch (e) {
        // What the console showed when a step could not go on, so the failure says why.
        const shown = await browser.contexts()[0]?.pages()[0];
        if (shown) {
          console.log(`the page when it stopped: ${(await shown.locator('body').innerText().catch(() => '')).slice(0, 1500)}`);
        }
        throw e;
      } finally {
        await browser.close();
      }
    },
    { platform: true, tools: { env: { ...fakes.info.settings, ...plugins } }, kbEnv: { ...plugins, OPS_TOOLS_URL: `http://127.0.0.1:${TOOLS_PORT}` } },
  );
} finally {
  fakes.child.stdin.end();
  setTimeout(() => fakes.child.kill('SIGTERM'), 10_000).unref();
}

finish();
