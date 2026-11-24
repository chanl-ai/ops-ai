// uc-779 a watched folder brings files in, ui layer: docs/usecases/files-service/a-watched-folder-brings-files-in.md.
// The built-in SharePoint plugin (the copy every stack ships) runs in the stack's tools-service against its fake (docs/usecases/lib/fake_sharepoint_confluence.py,
// run as a script with --oversize: one file in the Policies folder Graph reports as 30 MB), and files-service checks the
// watch through it. James (builder) watches a folder from Files › Watched folders before and after the team connects
// SharePoint, presses Check now and opens a file it brought in; Ravi (viewer) reads the same list. Priya (admin) and Sam
// (security) connect SharePoint through the API, as uc-678 proves at its own layers. The list's loading, empty and error
// states are drawn by intercepting its one request. Every screen is shot at 1440 and 390 wide.
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { FILES_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

const JAMES = 'j.richardson@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const NAME = `Policies folder ${TAG}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const asPerson = async (email) => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const isList = (url) => new URL(url).pathname.endsWith('/v1/watches');

/** The fakes, started from their script; resolves with what it printed, and a reader of the lines it prints next. */
async function startFakes() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_sharepoint_confluence.py'), '--oversize'], {
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

/** A signed-in page; page errors, console errors (while `watching.on`) and sideways scroll are collected per page. */
async function signIn(browser, consoleUrl, email, problems, watching) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => problems.push(`${email} error ${e.message}`));
  page.on('console', (m) => m.type() === 'error' && watching.on && problems.push(`${email} console ${m.text()}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

/** Shoots a screen at both widths and records any width at which the page scrolls sideways. */
async function shoot(page, name, show, wide) {
  await shootBothWidths(page, 'files', name, async () => {
    await show();
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) wide.push(`${name} at ${page.viewportSize().width}`);
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
}

const fakes = await startFakes();
// No working copy replaces the built-in plugins, so the run reads the copy that ships.
const plugins = { OPS_PLUGIN_PATHS: '[]' };

try {
  await withUiStack(
    async (consoleUrl) => {
      const browser = await chromium.launch();
      const problems = [];
      const wide = [];
      const watching = { on: true };
      const watches = `${consoleUrl}/data/files/watches`;
      try {
        const page = await signIn(browser, consoleUrl, JAMES, problems, watching);

        // S3: before the team connects SharePoint, step 1 says so, links to its app page and keeps Next disabled.
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('watch-add').click({ timeout: 120_000 });
        const dialog = page.getByTestId('watch-folder-dialog');
        const none = dialog.getByTestId('watch-no-connection');
        await none.waitFor({ timeout: 60_000 });
        const links = await dialog.getByTestId('watch-connect-link').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
        const next = dialog.getByTestId('watch-next');
        check(
          '11 with SharePoint not yet on for the team, step 1 says no connection can list files, opens Apps, and Next is disabled with its reason',
          links.length === 1 && links[0] === '/data/connectors' && (await next.isDisabled()) && (await next.innerText()).includes('connect an app first'),
          { links, disabled: await next.isDisabled(), next: await next.innerText() },
        );
        await shoot(page, 'uc-779-no-connection', async () => none.waitFor(), wide);
        await dialog.getByRole('button', { name: 'Cancel' }).click();

        // The team's set-up, through the API: Security allows the hosts and range, Priya signs SharePoint in.
        const admin = { Authorization: `Bearer ${await tokenFor('p.shah@harborpine.example')}`, 'X-Team-Id': 'team_ops' };
        const security = { Authorization: `Bearer ${await tokenFor('s.adeyemi@harborpine.example')}`, 'X-Team-Id': 'team_security' };
        fakes.child.stdin.write(`${JSON.stringify({ tools: `http://127.0.0.1:${TOOLS_PORT}`, admin, security })}\n`);
        const done = JSON.parse(await fakes.next());
        check('12 the team signs SharePoint in through Microsoft', done.sharepoint.done === 200, done.sharepoint);

        // James watches the Policies Library: name, then the shared scope step's pickers, then the review.
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByTestId('watch-add').click({ timeout: 120_000 });
        await dialog.getByTestId('watch-name').fill(NAME);
        await dialog.getByTestId('watch-connection').waitFor({ timeout: 60_000 });
        await next.click();
        const sites = dialog.getByTestId('wf-sites-picker');
        const libraries = dialog.getByTestId('wf-libraries-picker');
        const stepTwo = await dialog.innerText();
        check('21 step 2 shows no developer text: no ids and no "page path"', !/page path|\bids?\b|_id\b/i.test(stepTwo), stepTwo.slice(0, 800));
        await sites.getByTestId('wf-sites-option').filter({ hasText: 'Human Resources' }).click({ timeout: 60_000 });
        await libraries.getByTestId('wf-libraries-option').filter({ hasText: 'Policies Library' }).click({ timeout: 60_000 });
        await libraries.getByText(/^1 picked/).waitFor({ timeout: 60_000 });
        await next.click();
        const notice = dialog.getByTestId('watch-team-notice');
        await notice.waitFor({ timeout: 30_000 });
        const review = await dialog.innerText();
        check('13 the review names the folders by name and says everyone on the team can read the files', review.includes('Human Resources') && review.includes('Policies Library') && review.includes('Everyone on the team can read these files'), review.slice(0, 600));
        await shoot(page, 'uc-779-review', async () => notice.waitFor(), wide);
        const creating = armed(page.waitForResponse((r) => r.request().method() === 'POST' && isList(r.url()), { timeout: 60_000 }));
        await dialog.getByTestId('watch-create').click();
        const created = await creating;
        const watch = created ? (await created.json()).data : {};
        check('13 Watch a folder saves the watch', created?.status() === 201 && !!watch.id, created ? await created.text() : 'no request');
        const row = page.locator('tr', { has: page.getByTestId(`watch-row-${watch.id}`) });
        await row.waitFor({ timeout: 60_000 });

        const named = await row.getByText('SharePoint').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const beforeCheck = await row.innerText();
        check('22 before the first check the row names the app by its display name', named && /Not checked yet/.test(beforeCheck), beforeCheck);

        // S2: Check now from the row menu shows Checking…, then the time, the count and the failed file with its size.
        await row.getByRole('button', { name: 'Open menu' }).click();
        await page.getByRole('menuitem', { name: 'Check now' }).click();
        const running = await page.getByTestId(`watch-checking-${watch.id}`).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const failedCell = page.getByTestId(`watch-failed-${watch.id}`);
        await failedCell.waitFor({ timeout: 120_000 });
        const shown = await row.innerText();
        const H = await asPerson(JAMES);
        const events = (await (await fetch(`${files}/v1/watches/${watch.id}/events`, { headers: H })).json()).data?.data ?? [];
        const failedEvent = events.find((e) => e.kind === 'failed');
        const mb = `${(fakes.info.oversize.size / 1024 ** 2).toFixed(1)} MB`;
        check(
          '14 Check now shows the check running, then the time, three files brought in and the 30 MB file as failed with its size, without a reload',
          running && /3 files brought in/.test(shown) && /3 files/.test(await page.getByTestId(`watch-files-${watch.id}`).innerText()) && shown.includes(fakes.info.oversize.name) && shown.includes(mb) && failedEvent?.size === fakes.info.oversize.size && /ago|just now|seconds?/i.test(shown),
          { running, shown, failedEvent },
        );
        const failedText = await failedCell.innerText();
        const headers = await page.locator('thead').innerText();
        check(
          '23 the failed file sits in the In Files cell with a next step and a help link, and there is no Needs attention column',
          (await row.getByTestId(`watch-files-${watch.id}`).locator('xpath=..').getByTestId(`watch-failed-${watch.id}`).count()) === 1 && /Split it or make it smaller/.test(failedText) && (await failedCell.getByTestId(`watch-failed-help-${watch.id}`).count()) === 1 && !/Needs attention/.test(headers),
          { failedText, headers },
        );
        const guideLink = await failedCell.getByTestId(`watch-failed-help-${watch.id}`).getAttribute('href');
        const guideFile = await readFile(join(ROOT, 'docs/guide/watch-a-folder.md'), 'utf8');
        const guideNav = await readFile(join(ROOT, 'apps/docs/src/lib/nav.mjs'), 'utf8');
        const guideIndex = await readFile(join(ROOT, 'docs/guide/README.md'), 'utf8');
        check(
          '24 the guide page on watching a folder exists with a Failed files section, is linked from the guide index and the docs nav, and the failed file links to it',
          /^## Failed files/m.test(guideFile) && guideIndex.includes('watch-a-folder.md') && guideNav.includes('guide/watch-a-folder.md') && /\/docs\/guide\/watch-a-folder#failed-files$/.test(guideLink ?? ''),
          { guideLink },
        );
        await page.setViewportSize({ width: 390, height: 900 });
        const phoneRow = page.locator('tr', { has: page.getByTestId(`watch-row-${watch.id}`) });
        const phoneText = await phoneRow.innerText();
        const phoneScroll = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
        check('25 at 390 the row shows the last check and the failed file with no sideways scroll', /brought in/.test(phoneText) && phoneText.includes('failed') && !phoneScroll, { phoneText, phoneScroll });
        await page.setViewportSize({ width: 1440, height: 1000 });
        // The failed file is drawn in the In Files cell from 640 wide and under the folder's name below it.
        await shoot(page, 'uc-779-watched-folders', async () => page.locator(`[data-testid="watch-failed-${watch.id}"], [data-testid="watch-failed-stacked-${watch.id}"]`).locator('visible=true').first().waitFor(), wide);

        // The file page's Source section, for a file the check brought in.
        const leave = events.find((e) => e.kind === 'new' && String(e.path).endsWith('leave.md'));
        await page.goto(`${consoleUrl}/data/files/${leave?.fileId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const source = page.getByTestId('file-source');
        await source.waitFor({ timeout: 60_000 });
        const said = await source.innerText();
        check('15 a brought-in file\'s page names its watched folder and its path at the source', said.includes(NAME) && said.includes('Policies › leave.md'), said);
        await shoot(page, 'uc-779-file-source', async () => source.waitFor(), wide);

        // S1: Ravi reads the list with no Watch a folder and no row menu, and a direct call is refused.
        const ravi = await signIn(browser, consoleUrl, RAVI, problems, watching);
        await ravi.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const raviRow = ravi.locator('tr', { has: ravi.getByTestId(`watch-row-${watch.id}`) });
        await raviRow.waitFor({ timeout: 120_000 });
        const R = await asPerson(RAVI);
        const add = await fetch(`${files}/v1/watches`, { method: 'POST', headers: R, body: JSON.stringify({ name: 'Ravi folder', plugin: watch.plugin, source: watch.source, connectionId: watch.connectionId, values: watch.values }) });
        const checkNow = await fetch(`${files}/v1/watches/${watch.id}/check`, { method: 'POST', headers: R });
        check(
          '16 Ravi, a viewer, sees the watch with no Watch a folder or Check now, and a direct add or check is 403',
          (await ravi.getByTestId('watch-add').count()) === 0 && (await raviRow.getByRole('button', { name: 'Open menu' }).count()) === 0 && (await raviRow.innerText()).includes(fakes.info.oversize.name) && add.status === 403 && checkNow.status === 403,
          { add: add.status, check: checkNow.status, buttons: await ravi.getByTestId('watch-add').count() },
        );
        await shoot(ravi, 'uc-779-viewer', async () => raviRow.waitFor(), wide);

        // S4: Knowledge's Add source keeps its SharePoint step 2: both pickers, the path rules and the preview.
        await page.goto(`${consoleUrl}/data/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'New knowledge base' }).first().click({ timeout: 120_000 });
        await page.getByLabel('Name').fill(`Policies ${TAG}`);
        const made = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/knowledge-bases'), { timeout: 60_000 }));
        await page.getByTestId('kb-create').click();
        const kbId = (await (await made).json()).data.id;
        await page.waitForURL(`**/knowledge/${kbId}**`, { timeout: 60_000 });
        await page.getByTestId('kb-add-source').click({ timeout: 60_000 });
        await page.getByTestId('kb-add-apps').click();
        const wizard = page.getByTestId('add-source-wizard');
        await wizard.getByTestId('add-source-kind-files').click({ timeout: 60_000 });
        await wizard.getByTestId('add-source-next').click();
        const kbSites = wizard.getByTestId('as-sites-picker');
        await kbSites.getByTestId('as-sites-option').filter({ hasText: 'Human Resources' }).click({ timeout: 60_000 });
        const kbLibs = wizard.getByTestId('as-libraries-picker');
        await kbLibs.getByText(/^0 picked · 2 listed/).waitFor({ timeout: 60_000 });
        const step2 = await wizard.innerText();
        // SharePoint's source declares no preview tool, so its step 2 has never shown one, on either dialog.
        check(
          '17 Knowledge\'s Add source step 2 for SharePoint still shows the name, the sites and libraries pickers and the include and exclude rules, and no preview',
          (await wizard.getByTestId('add-source-name').count()) === 1 && /Include/.test(step2) && /Exclude/.test(step2) && (await wizard.getByTestId('add-source-preview').count()) === 0,
          step2.slice(0, 800),
        );
        await shoot(page, 'uc-779-knowledge-step-2', async () => kbLibs.waitFor(), wide);

        // The list's loading, empty and error states, by intercepting its one GET.
        let held;
        await page.route((u) => isList(u.href), (route) => (route.request().method() === 'GET' ? (held = route) : route.continue()));
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const skeleton = page.getByTestId('page-skeleton');
        await skeleton.waitFor({ timeout: 60_000 });
        await shoot(page, 'uc-779-loading', async () => skeleton.waitFor(), wide);
        check('18 while the list loads the page shows its skeleton', await skeleton.isVisible());
        await held?.continue();
        await page.unroute((u) => isList(u.href));

        await page.route((u) => isList(u.href), async (route) => {
          if (route.request().method() !== 'GET') return route.continue();
          const real = await route.fetch();
          const json = await real.json();
          json.data = { ...json.data, data: [], total: 0 };
          return route.fulfill({ response: real, json });
        });
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const empty = page.getByText('No watched folders yet');
        await empty.waitFor({ timeout: 60_000 });
        check('18 a team with no watches sees the empty state with Watch a folder', await page.getByRole('button', { name: 'Watch a folder' }).first().isVisible());
        await shoot(page, 'uc-779-empty', async () => empty.waitFor(), wide);
        await page.unroute((u) => isList(u.href));

        // A refused request logs a console error by design; it is not counted for this state.
        watching.on = false;
        await page.route((u) => isList(u.href), (route) => (route.request().method() === 'GET' ? route.fulfill({ status: 500, json: { error: { code: 'internal', message: 'files-service failed' } } }) : route.continue()));
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const failed = page.getByText('Couldn’t load watched folders');
        await failed.waitFor({ timeout: 90_000 });
        check('18 a list request that fails says so with Try again', await page.getByRole('button', { name: /Try again|Retrying/ }).isVisible());
        await shoot(page, 'uc-779-error', async () => failed.waitFor(), wide);
        await page.unroute((u) => isList(u.href));
        watching.on = true;

        // The running and refused states, drawn on the real list by changing what its one request answers: a check
        // in progress, then a check refused for its sign-in and one refused because apps could not be reached.
        const answered = (change) => async (route) => {
          if (route.request().method() !== 'GET') return route.continue();
          const real = await route.fetch();
          const json = await real.json();
          json.data = { ...json.data, data: json.data.data.map((w) => (w.id === watch.id ? change(w) : w)) };
          return route.fulfill({ response: real, json });
        };
        await page.route((u) => isList(u.href), answered((w) => ({ ...w, checking: true })));
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const checking = page.getByTestId(`watch-checking-${watch.id}`);
        const checkingShown = page.getByText('Checking…').locator('visible=true').first();
        await checking.waitFor({ timeout: 60_000 });
        check('19 a check in progress shows Checking on its row', await checking.isVisible());
        await shoot(page, 'uc-779-checking', async () => checkingShown.waitFor({ timeout: 30_000 }), wide);
        await page.unroute((u) => isList(u.href));
        const refusedAs = (code, stopped) => (w) => ({ ...w, checking: false, lastCheckAt: new Date().toISOString(), lastCheck: { ...w.lastCheck, status: 'refused', code, stopped } });
        await page.route((u) => isList(u.href), answered(refusedAs('needs_reconnect', 'The connection refused its sign-in.')));
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const alert = page.locator('[data-testid="watch-refused"][data-code="needs_reconnect"]');
        await alert.waitFor({ timeout: 60_000 });
        const alertText = await alert.innerText();
        check('19 a check refused for its sign-in says so with Reconnect', /refused the sign-in/.test(alertText) && (await alert.getByTestId('watch-reconnect').isVisible()), alertText);
        await shoot(page, 'uc-779-refused', async () => alert.waitFor(), wide);
        await page.unroute((u) => isList(u.href));
        await page.route((u) => isList(u.href), answered(refusedAs('unreachable', 'Apps could not be reached.')));
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const away = page.locator('[data-testid="watch-refused"][data-code="unreachable"]');
        await away.waitFor({ timeout: 60_000 });
        const awayText = await away.innerText();
        check('19 a check refused because apps could not be reached says that, with no Reconnect', /could not be reached/.test(awayText) && !/sign-in/.test(awayText) && (await away.getByTestId('watch-reconnect').count()) === 0, awayText);
        await page.unroute((u) => isList(u.href));
        // A check that stopped partial says so with its reason, never the green tick of a finished one.
        const partialAs = (code, stopped) => (w) => ({ ...w, checking: false, lastCheckAt: new Date().toISOString(), lastCheck: { ...w.lastCheck, status: 'partial', code, stopped } });
        await page.route((u) => isList(u.href), answered(partialAs('fetch_failed', 'Some files could not be fetched; the next check tries them again.')));
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const partial = page.locator(`[data-testid="watch-last-check-${watch.id}"][data-status="partial"]`);
        const partialShown = await partial.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const partialText = partialShown ? await partial.innerText() : await row.innerText();
        check('19 a check that stopped partial says Partial with its reason and no green tick', partialShown && /Partial/.test(partialText) && /could not be fetched/.test(partialText) && (await partial.locator('.text-success').count()) === 0, partialText);
        if (partialShown) await shoot(page, 'uc-779-partial', async () => page.getByText(/^Partial/).locator('visible=true').first().waitFor({ timeout: 30_000 }), wide);
        await page.unroute((u) => isList(u.href));

        // Stop watching replaces Delete, and says what happens to the files.
        await page.goto(watches, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const stopRow = page.locator('tr', { has: page.getByTestId(`watch-row-${watch.id}`) });
        await stopRow.waitFor({ timeout: 60_000 });
        await stopRow.getByRole('button', { name: 'Open menu' }).click();
        const hasDelete = await page.getByRole('menuitem', { name: 'Delete' }).count();
        await page.getByRole('menuitem', { name: 'Stop watching' }).click();
        const stopDialog = page.getByTestId('watch-stop-dialog');
        await stopDialog.waitFor({ timeout: 30_000 });
        const stopText = await stopDialog.innerText();
        check('26 the row action is Stop watching, not Delete, and its dialog says the files stay in Files', hasDelete === 0 && /already in Files stay there/.test(stopText), { hasDelete, stopText });
        await shoot(page, 'uc-779-stop-watching', async () => stopDialog.waitFor(), wide);
        await stopDialog.getByTestId('watch-stop-confirm').click();
        await stopRow.waitFor({ state: 'detached', timeout: 60_000 });
        const kept = await fetch(`${files}/v1/files/${leave?.fileId}`, { headers: H });
        check('26 after Stop watching the row is gone and a brought-in file is still in Files', kept.status === 200, kept.status);

        check('20 no sideways scroll at 1440 or 390 on any screen', wide.length === 0, wide);
        check('20 no page or console errors', problems.length === 0, problems);
      } catch (e) {
        const shown = browser.contexts()[0]?.pages()[0];
        if (shown) console.log(`the page when it stopped: ${(await shown.locator('body').innerText().catch(() => '')).slice(0, 1500)}`);
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
