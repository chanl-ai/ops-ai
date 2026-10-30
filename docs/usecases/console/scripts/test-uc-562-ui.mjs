// uc-562 Every console page reads well on a phone and on a desktop, ui layer: docs/usecases/console/phone-and-desktop.md
// (c-562). The demo stack: James starts a credit that waits on a person, offered as two options, and Maya holds the task;
// James opens a case. Maya checks one page per class the console UI sweep found: the decision starts unpicked, phone
// lists show the name and a fade where more columns sit, search boxes show their placeholder, descriptions read in full,
// tab strips scroll with a cue, record and Settings pages show where they are and a way back, Profile shows her, the
// sidebar has one Human Tasks count, Tool calls stops loading and Tools logs no error. Screenshots go to
// evidenceDir('562', 'uc').
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, KB_PORT, PLATFORM_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = evidenceDir('562', 'uc');
const LISTS = ['/agents', '/cases', '/tools', '/files', '/knowledge', '/skills'];

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 180_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

// UC562_STEPS=1,2 runs only those steps (setup always runs).
const ONLY = process.env.UC562_STEPS?.split(',').map((x) => x.trim());
async function step(name, body) {
  if (ONLY && !ONLY.includes(name.split(' ')[0])) return;
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

// What a phone list shows: the header cells in view, whether the Id column is drawn, and the edge fade.
const tableState = () => {
  const c = document.querySelector('main [data-slot=table-container]');
  if (!c) return null;
  const cr = c.getBoundingClientRect();
  const heads = [...c.querySelectorAll('thead th')].filter((h) => h.getBoundingClientRect().width > 0);
  const inView = heads.filter((h) => { const r = h.getBoundingClientRect(); return r.left >= cr.left - 1 && r.right <= cr.right + 1; }).map((h) => h.innerText.trim()).filter(Boolean);
  const fade = c.parentElement?.querySelector('[data-testid=table-edge-fade]');
  const fs = fade && getComputedStyle(fade);
  return { inView, idShown: heads.some((h) => h.innerText.trim() === 'Id'), scrolls: c.scrollWidth > c.clientWidth + 1, atEnd: c.scrollLeft + c.clientWidth >= c.scrollWidth - 1, fade: !!fade && fs.display !== 'none' && Number(fs.opacity) > 0.01, fadeImage: fs?.backgroundImage ?? null };
};
// Placeholders that do not fit their box, measured as the sweep does.
const cutPlaceholders = () => {
  const ctx = document.createElement('canvas').getContext('2d');
  return [...document.querySelectorAll('main input[placeholder]')].filter((i) => i.getBoundingClientRect().width > 0 && !i.value).flatMap((i) => {
    const cs = getComputedStyle(i);
    ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const room = i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    return ctx.measureText(i.placeholder).width > room + 1 ? [i.placeholder] : [];
  });
};

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const maya = as(await tokenFor(MAYA));
    // A plain workflow whose person step offers two options, so the task exists without any model call.
    const yaml = ['schemaVersion: 2', 'id: uc562_credit', 'name: Provisional credit (uc-562)', 'nodes:', '  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}', '  - id: review', '    type: ops.flow.humanReview', '    typeVersion: 1', '    name: Provisional credit', '    parameters:', '      title: Provisional credit for Marcus Bell', '      options: [{name: approve, label: Give the provisional credit}, {name: reject, label: Decline the credit}]', '  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}', '  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}', 'connections:', '  - {from: {node: start, port: payload}, to: {node: review, port: in}}', '  - {from: {node: review, port: approve}, to: {node: approved, port: in}}', '  - {from: {node: review, port: reject}, to: {node: rejected, port: in}}'].join('\n');
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ yaml }) });
    if (saved.status >= 300) throw new Error(`setup: saving the workflow answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
    const req = await json(await fetch(`${agents}/v1/workflows/definitions/uc562_credit/publish-requests`, { method: 'POST', headers: james, body: JSON.stringify({}) }));
    if (req?.status !== 'approved') await fetch(`${agents}/v1/publish-requests/${req?.id}/decision`, { method: 'POST', headers: maya, body: JSON.stringify({ decision: 'approved' }) });
    // Two credits: step 1 may decide its own (that is the defect it looks for), so the queue in step 5 reads the other.
    const start = async () => (await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: 'uc562_credit', input: { amount: 250 } }) })))?.runId;
    const runId = await start();
    const queuedRun = await start();
    const stateOf = async (id) => (await json(await fetch(`${agents}/v1/runs/${id}`, { headers: james })))?.status;
    const runState = () => stateOf(runId);
    const waiting = await until(async () => ((await stateOf(runId)) === 'waiting' && (await stateOf(queuedRun)) === 'waiting' ? 'waiting' : null));
    const reviewId = `${runId}:review:1`;
    const queuedId = `${queuedRun}:review:1`;
    const assigned = await json(await fetch(`${agents}/reviews/assign`, { method: 'POST', headers: maya, body: JSON.stringify({ ids: [reviewId, queuedId], assignee: MAYA }) }));
    const made = await json(await fetch(`${agents}/v1/cases`, { method: 'POST', headers: james, body: JSON.stringify({ subject: 'Chargeback evidence for Marcus Bell', priority: 'high', customerId: 'C-2201', customerName: 'Marcus Bell' }) }));
    check('0 setup: a two-option credit task held by Maya and a case', waiting === 'waiting' && assigned?.updated?.length === 2 && !!made?.id, { runId, waiting, assigned, caseId: made?.id });

    const browser = await chromium.launch();
    const errors = [];
    const consoleErrors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      page.on('console', (m) => m.type() === 'error' && consoleErrors.push({ at: new URL(page.url()).pathname, text: m.text().slice(0, 200) }));
      const go = async (path, width = 1440, scheme = 'light') => {
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize({ width, height: width < 500 ? 844 : 900 });
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'load' });
        await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => undefined);
        await page.waitForTimeout(1200);
      };
      const shot = (name) => page.screenshot({ path: join(SHOTS, `${name}.png`) });

      await step('1 a Human Task opens with no option picked and Decide waiting for a pick', async () => {
        await go(`/reviews?review=${encodeURIComponent(reviewId)}`);
        const form = page.locator('[data-testid=option-decision-form][data-layout=panel]');
        await form.waitFor();
        const checked = await form.locator('[role=radio][data-state=checked], [role=radio][aria-checked=true]').count();
        const decide = page.getByTestId('decide');
        const before = { label: (await decide.innerText()).trim(), disabled: await decide.isDisabled() };
        await decide.click({ force: true, timeout: 5000 }).catch(() => undefined);
        await page.waitForTimeout(2000);
        const stillWaiting = (await runState()) === 'waiting';
        await shot('decision-unpicked-1440');
        let after = null;
        if (stillWaiting && (await page.getByTestId('option-reject').count())) {
          await page.getByTestId('option-reject').click();
          const picked = (await page.getByTestId('option-reject').locator('span.font-medium').first().innerText()).split('\n')[0].trim();
          after = { picked, label: (await decide.innerText()).trim(), disabled: await decide.isDisabled() };
        }
        check('1 a Human Task opens with no option picked and Decide waiting for a pick', checked === 0 && before.label === 'Pick a decision' && before.disabled && stillWaiting && !!after?.picked && after.label === after.picked && !after.disabled, { checked, before, stillWaiting, after });
      });

      await step('2 a phone list shows the name, no Id, and a fade while more columns sit past the edge', async () => {
        const seen = {};
        for (const scheme of ['light', 'dark']) {
          await go('/agents', 390, scheme);
          await page.locator('main tbody tr').first().waitFor({ timeout: 30_000 });
          const start = await page.evaluate(tableState);
          await shot(`agents-390-${scheme}`);
          await page.evaluate(() => { const c = document.querySelector('main [data-slot=table-container]'); c.scrollLeft = c.scrollWidth; });
          await page.waitForTimeout(400);
          const end = await page.evaluate(tableState);
          seen[scheme] = { start, end };
        }
        const ok = (s) => s.start && !s.start.idShown && s.start.inView[0] !== 'Id' && s.start.inView.length > 0 && s.start.scrolls && s.start.fade && /gradient/.test(s.start.fadeImage ?? '') && s.end.atEnd && !s.end.fade;
        const cut = {};
        for (const width of [1024, 1440]) for (const path of LISTS) {
          await go(path, width);
          const c = await page.evaluate(cutPlaceholders);
          if (c.length) cut[`${width} ${path}`] = c;
        }
        check('2 a phone list shows the name, no Id, and a fade while more columns sit past the edge', ok(seen.light) && ok(seen.dark) && !Object.keys(cut).length, { seen, cut });
      });

      await step('3 on a phone, descriptions read in full, header actions wrap, tab strips scroll with a cue, and a record page shows a way back', async () => {
        await go('/cases', 390);
        const clamped = await page.evaluate(() => { const d = document.querySelector('[data-testid=page-description]'); return d ? d.scrollHeight > d.clientHeight + 1 : null; });
        await go('/skills', 390);
        // Header actions only: controls inside a sideways scroller (view tabs, tables) are meant to sit past the edge.
        const offEdge = await page.evaluate(() => {
          const scrolls = (el) => { for (let a = el.parentElement; a; a = a.parentElement) if (/auto|scroll/.test(getComputedStyle(a).overflowX)) return true; return false; };
          return [...document.querySelectorAll('[data-testid=page-header] button, [data-testid=page-header] a[href]')].filter((b) => { const r = b.getBoundingClientRect(); return r.width > 0 && r.right > innerWidth + 1 && !scrolls(b); }).map((b) => b.innerText.trim().slice(0, 40));
        });
        await go('/files', 390);
        const tabs = await page.evaluate(() => { const t = document.querySelector('main [role=tablist]'); if (!t) return null; const f = t.parentElement?.querySelector('[data-testid=tabs-edge-fade]'); return { scrolls: t.scrollWidth > t.clientWidth + 1, overflow: getComputedStyle(t).overflowX, fade: !!f && Number(getComputedStyle(f).opacity) > 0.01 }; });
        await shot('files-tabs-390');
        // A touch screen: no hover, so the way back has to show at rest.
        const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
        const phone = await ctx.newPage();
        phone.on('pageerror', (e) => errors.push(`phone: ${e.message}`));
        await phone.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded' });
        await phone.getByLabel('Work email').fill(MAYA);
        await phone.getByLabel('Password').fill(PASSWORD);
        await phone.getByTestId('login-submit').click();
        await phone.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        // An agent's page: a record page whose icon holds the back arrow, shown on hover on a desktop.
        await phone.goto(`${consoleUrl}/agents`, { waitUntil: 'load' });
        const agentHref = await phone.locator('main tbody tr a[href^="/agents/"]').first().getAttribute('href', { timeout: 30_000 });
        await phone.goto(`${consoleUrl}${agentHref}`, { waitUntil: 'load' });
        await phone.getByTestId('page-back-icon').waitFor({ timeout: 30_000 });
        await phone.waitForTimeout(800);
        const back = await phone.evaluate(() => ({ coarse: matchMedia('(pointer: coarse)').matches, arrow: Number(getComputedStyle(document.querySelector('[data-testid=page-back-icon] > svg')).opacity), crumbs: [...document.querySelectorAll('header nav[aria-label=Breadcrumb] a[href]')].map((a) => a.getAttribute('href')) }));
        await phone.screenshot({ path: join(SHOTS, 'agent-record-390-touch.png') });
        await ctx.close();
        check('3 on a phone, descriptions read in full, header actions wrap, tab strips scroll with a cue, and a record page shows a way back', clamped === false && !offEdge.length && !!tabs && tabs.scrolls && /auto|scroll/.test(tabs.overflow) && tabs.fade && back.coarse && back.arrow > 0.5 && back.crumbs.includes('/agents'), { clamped, offEdge, tabs, back });
      });

      await step('4 Settings pages name their place, personal pages have no duplicate tabs, and Profile shows Maya', async () => {
        await go('/settings/team/webhooks');
        const s = await page.evaluate(() => ({ crumbs: [...document.querySelectorAll('header nav[aria-label=Breadcrumb] > span')].map((c) => c.innerText.replace('/', '').trim()), links: [...document.querySelectorAll('header nav[aria-label=Breadcrumb] a[href]')].map((a) => a.getAttribute('href')), title: document.querySelector('[data-testid=page-title], main h1')?.innerText.trim() }));
        const broken = [];
        for (const href of s.links) {
          const r = await page.request.get(`${consoleUrl}${href}`);
          if (r.status() >= 400) broken.push(`${href} ${r.status()}`);
        }
        await go('/settings/account');
        await page.getByTestId('account-profile').waitFor({ timeout: 30_000 }).catch(() => undefined);
        const p = await page.evaluate(() => ({ tabs: document.querySelectorAll('main [role=tablist]').length, text: document.querySelector('[data-testid=account-profile]')?.innerText ?? '', nameEditable: !!document.querySelector('[data-testid=account-profile] input:not([readonly]):not([disabled])') }));
        await shot('account-profile-1440');
        check('4 Settings pages name their place, personal pages have no duplicate tabs, and Profile shows Maya', s.crumbs.at(-1) === s.title && s.title === 'Webhooks' && s.links.includes('/settings') && !broken.length && p.tabs === 0 && p.text.includes(MAYA) && !/Richardson/.test(p.text) && !p.nameEditable, { s, broken, p: { ...p, text: p.text.slice(0, 200) } });
      });

      await step('5 the queue shows amount and customer, one Human Tasks count, Tool calls settles, and Tools has no error', async () => {
        await go('/reviews');
        const item = page.getByTestId(`queue-item-${queuedId}`);
        await item.waitFor({ timeout: 30_000 });
        const cutInQueue = await item.evaluate((el) => [...el.querySelectorAll('*')].filter((x) => x.childElementCount === 0 && x.innerText?.trim() && x.scrollWidth > x.clientWidth + 1).map((x) => x.innerText.trim()));
        const mine = (await json(await fetch(`${agents}/reviews?view=mine&pageSize=1`, { headers: maya })))?.viewCounts?.mine;
        const counts = { overview: await page.getByTestId('sidebar-overview-count').count(), reviews: Number((await page.getByTestId('sidebar-count-reviews').innerText().catch(() => 'NaN')).trim()) };
        await go('/logs/tool-calls');
        await page.waitForTimeout(4000);
        const calls = await page.evaluate(() => ({ skeletons: document.querySelectorAll('main [data-slot=skeleton], main .animate-pulse').length, notServed: /Totals are not served yet/.test(document.querySelector('main')?.innerText ?? '') }));
        consoleErrors.length = 0;
        await go('/tools');
        await page.locator('main tbody tr').first().waitFor({ timeout: 30_000 });
        const tools = await page.evaluate(() => ({ nested: document.querySelectorAll('main a a').length, opens: [...document.querySelectorAll('main tbody tr')].map((r) => r.querySelectorAll('[data-row-open]').length), secrets: document.querySelectorAll('main [data-testid^=unset-secrets-]').length }));
        const toolErrors = consoleErrors.filter((e) => e.at === '/tools').map((e) => e.text);
        let secretsLanded = null;
        if (tools.secrets) {
          await page.locator('main [data-testid^=unset-secrets-]').first().click();
          await page.waitForURL((u) => u.pathname === '/settings/security/secrets', { timeout: 15_000 }).catch(() => undefined);
          secretsLanded = new URL(page.url()).pathname;
        }
        check('5 the queue shows amount and customer, one Human Tasks count, Tool calls settles, and Tools has no error', !cutInQueue.length && counts.overview === 0 && counts.reviews === mine && mine >= 1 && calls.skeletons === 0 && calls.notServed && tools.nested === 0 && tools.opens.every((n) => n === 1) && !toolErrors.length && tools.secrets > 0 && secretsLanded === '/settings/security/secrets', { cutInQueue, counts, mine, calls, tools, toolErrors, secretsLanded });
      });

      await step('6 a builder sees one Runs list and one Workflows list, with no engine names', async () => {
        const OLD = /Runner · v2|Graph · v1|Graph workflow|earlier engine/;
        await go('/workflows/runs');
        await page.getByTestId('runner-runs').waitFor({ timeout: 30_000 });
        const runs = await page.evaluate((old) => ({ tabs: document.querySelectorAll('[data-testid^=runs-kind-]').length, old: new RegExp(old).test(document.querySelector('main')?.innerText ?? '') }), OLD.source);
        await shot('runs-one-list-1440');
        await go('/workflows');
        await page.locator('main tbody tr').first().waitFor({ timeout: 30_000 });
        const list = await page.evaluate((old) => ({ kind: document.querySelectorAll('[data-testid=workflow-kind]').length, old: new RegExp(old).test(document.querySelector('main')?.innerText ?? ''), links: [...document.querySelectorAll('main tbody a[href^="/workflows/"]')].map((a) => a.getAttribute('href')).filter((h) => !h.startsWith('/workflows/definitions/') && !h.startsWith('/workflows/runs')) }), OLD.source);
        // New workflow is a builder's button; James builds, Maya approves.
        const builder = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await builder.goto(`${consoleUrl}/workflows`, { waitUntil: 'load' });
        await builder.getByRole('button', { name: 'New workflow' }).first().click({ timeout: 30_000 });
        const dialog = builder.getByRole('dialog');
        await dialog.waitFor();
        const shapes = await dialog.locator('[role=radio]').count();
        const dialogOld = OLD.test(await dialog.innerText()) || /\bv[12]\b/.test(await dialog.innerText());
        await builder.context().close();
        check('6 a builder sees one Runs list and one Workflows list, with no engine names', runs.tabs === 0 && !runs.old && list.kind === 0 && !list.old && !list.links.length && shapes === 0 && !dialogOld, { runs, list, shapes, dialogOld });
      });

      await step('7 an old workflow link lands on the workflow, or says it is no longer available', async () => {
        await go('/workflows/uc562_credit');
        await page.waitForURL((u) => u.pathname === '/workflows/definitions/uc562_credit', { timeout: 30_000 }).catch(() => undefined);
        const current = new URL(page.url()).pathname;
        await go('/workflows/dispute_email');
        await page.waitForTimeout(1500);
        const gone = await page.evaluate(() => ({ path: location.pathname, text: document.querySelector('main')?.innerText ?? '', back: !!document.querySelector('main a[href="/workflows"]') }));
        await shot('old-workflow-link-1440');
        await go('/workflows/runs?run=thr_from_an_old_workflow');
        const oldRun = await page.evaluate(() => document.querySelector('main')?.innerText ?? '');
        check('7 an old workflow link lands on the workflow, or says it is no longer available', current === '/workflows/definitions/uc562_credit' && /no longer available/i.test(gone.text) && gone.back && /no longer available/i.test(oldRun), { current, gone: { ...gone, text: gone.text.slice(0, 200) }, oldRun: oldRun.slice(0, 200) });
      });

      await step('8 the services are down for 30 s and the page says so, then recovers by itself', async () => {
        await go('/cases');
        await page.locator('main tbody tr').first().waitFor({ timeout: 30_000 });
        // Every call to the agents service answers 503, as a service that is restarting or waking does.
        const down = (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":{"message":"unavailable"}}' });
        // Matched by port: the console may name the service's host differently from this script.
        const api = (u) => u.port === String(AGENTS_PORT);
        await page.route(api, down);
        const asked = [];
        const note = (r) => { const u = new URL(r.url()); if (u.origin !== new URL(consoleUrl).origin && asked.length < 12) asked.push(`${r.status()} ${u.host}${u.pathname}`); };
        page.on('response', note);
        const from = Date.now();
        // A page not opened yet, so nothing saved can stand in for the read: it has to ask the service.
        await page.goto(`${consoleUrl}/cases/${made.id}`, { waitUntil: 'load' });
        await page.waitForTimeout(6000);
        const during = await page.evaluate(() => ({ text: document.querySelector('main')?.innerText ?? '', said: /can.t reach its services/i.test(document.body.innerText) }));
        await shot('services-down-1440');
        page.off('response', note);
        await page.waitForTimeout(Math.max(0, 30_000 - (Date.now() - from)));
        // Coming back means a fresh read answers with no click.
        const fresh = page.waitForResponse((r) => new URL(r.url()).port === String(AGENTS_PORT) && new URL(r.url()).pathname.endsWith(`/v1/cases/${made.id}`) && r.status() === 200, { timeout: 30_000 }).then(() => true, () => false);
        await page.unroute(api, down);
        const refetched = await fresh;
        const back = refetched && (await page.getByText('Chargeback evidence for Marcus Bell').first().waitFor({ timeout: 15_000 }).then(() => true, () => false));
        const after = await page.evaluate(() => /can.t reach its services/i.test(document.body.innerText));
        check('8 the services are down for 30 s and the page says so, then recovers by itself', during.said && during.text.trim().length > 0 && back && !after, { said: during.said, asked, during: during.text.slice(0, 160), refetched, back, stillSaid: after });
      });

      await step('10 view counts wait for their list instead of showing 0', async () => {
        // The Human Tasks list is held for 5 s, as a slow service holds it; meanwhile no view may say it has 0.
        // A held request may outlive the step (the next page cancels it), so its late continue is let go quietly.
        const slow = async (route) => { await new Promise((r) => setTimeout(r, 5000)); await route.continue().catch(() => undefined); };
        const list = (u) => u.port === String(AGENTS_PORT) && u.pathname.endsWith('/reviews');
        await page.route(list, slow);
        await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'load' });
        await page.waitForTimeout(1500);
        const held = await page.locator('main [role=tab]').allInnerTexts();
        await page.unroute(list, slow);
        await page.waitForFunction(() => [...document.querySelectorAll('main [role=tab]')].some((t) => /·\s*\d/.test(t.textContent ?? '')), null, { timeout: 30_000 }).catch(() => undefined);
        const loaded = await page.locator('main [role=tab]').allInnerTexts();
        check('10 view counts wait for their list instead of showing 0', held.length > 0 && !held.some((t) => /·\s*0\b/.test(t)) && loaded.some((t) => /·\s*[1-9]/.test(t)), { held, loaded });
      });

      await step('11 a preview page says why in words and its sample parts offer no Save', async () => {
        await go('/settings/workspace');
        await page.getByTestId('setting-name').waitFor({ timeout: 30_000 });
        const general = await page.evaluate(() => ({
          reason: document.querySelector('[data-testid=preview-reason]')?.textContent?.trim() ?? null,
          sampleActions: [...document.querySelectorAll('[data-testid=sample-data-gate] button')].map((b) => b.textContent?.trim()).filter((t) => /^(Save|Upload)$/.test(t ?? '')),
          notes: document.querySelectorAll('[data-testid=sample-data-notice]').length,
        }));
        await shot('settings-general-preview-1440');
        await go('/settings/account');
        await page.getByTestId('account-profile').waitFor({ timeout: 30_000 });
        const account = await page.evaluate(() => ({ badge: document.querySelectorAll('[data-testid=preview-badge]').length, hint: /comes from your sign-in/.test(document.querySelector('[data-testid=account-profile]')?.textContent ?? '') }));
        check('11 a preview page says why in words and its sample parts offer no Save', !!general.reason && !general.sampleActions.length && general.notes <= 1 && account.badge === 0 && account.hint, { general, account });
      });

      await step('12 every Settings page with sample parts says why and offers no Save there, and nothing covers the Settings sidebar', async () => {
        await go('/settings/workspace', 1440);
        const routes = await page.evaluate(() => [...new Set([...document.querySelectorAll('[data-slot=sidebar] a[href^="/settings"]')].map((a) => a.getAttribute('href')))]);
        const bad = {};
        const gated = [];
        for (const r of routes) {
          await go(r, 1440);
          const seen = await page.evaluate(() => {
            const gates = [...document.querySelectorAll('[data-testid=sample-data-gate]')];
            if (!gates.length) return null;
            const actions = gates.flatMap((g) => [...g.querySelectorAll('button')]).filter((b) => b.getBoundingClientRect().width > 0 && /^(Save|Upload)/.test(b.textContent?.trim() ?? '')).map((b) => b.textContent.trim());
            return { reason: !!document.querySelector('[data-testid=preview-reason]'), actions };
          });
          if (seen) gated.push(r);
          if (seen && (!seen.reason || seen.actions.length)) bad[r] = seen;
        }
        // The last row of the Settings sidebar is reachable: what is drawn at its centre is the link itself.
        await go('/settings/workspace', 1440);
        const covered = await page.evaluate(() => {
          const a = [...document.querySelectorAll('[data-slot=sidebar] a')].find((x) => /My memory/.test(x.textContent ?? ''));
          if (!a) return 'no My memory row';
          const r = a.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + 12, r.top + r.height / 2);
          return a.contains(hit) ? null : (hit?.outerHTML ?? 'nothing').slice(0, 120);
        });
        check('12 every Settings page with sample parts says why and offers no Save there, and nothing covers the Settings sidebar', routes.length > 5 && !Object.keys(bad).length && !covered, { routes: routes.length, gated, bad, covered });
      });

      await step('13 an admin changes a source\'s schedule and is told it can\'t be saved yet; a save sends only what is stored', async () => {
        // kb-service stores a source's name, collection, owner, sensitivity and tags (SourcePatch); the rest it drops.
        const STORED = ['name', 'collection', 'owner', 'sensitivity', 'tags'];
        const kb = `http://127.0.0.1:${KB_PORT}`;
        const priya = as(await tokenFor('p.shah@harborpine.example'));
        let source = null;
        for (const row of (await json(await fetch(`${kb}/v1/sources?page=1&pageSize=50`, { headers: priya })))?.data ?? []) {
          if ((await json(await fetch(`${kb}/v1/sources/${row.id}`, { headers: priya })))?.canEdit) { source = row; break; }
        }
        if (!source) throw new Error('setup: no source Priya may change');
        const admin = await consoleSignIn(browser, consoleUrl, 'p.shah@harborpine.example', PASSWORD, errors);
        admin.setDefaultTimeout(60_000);
        await admin.goto(`${consoleUrl}/integrations/sources/${source.id}?tab=settings`, { waitUntil: 'load' });
        await admin.locator('#set-collection').waitFor({ timeout: 60_000 });
        const notice = await admin.getByTestId('source-settings-not-stored').count();
        const schedule = admin.getByRole('radiogroup', { name: 'Refresh schedule' });
        const scheduleOff = (await schedule.locator('[role=radio]').evaluateAll((els) => els.map((e) => e.hasAttribute('disabled') || e.closest('fieldset[disabled]') !== null))).every(Boolean);
        // A stored field still saves, and the request carries only stored fields.
        const sent = [];
        admin.on('request', (r) => { if (r.method() === 'PATCH' && r.url().includes(`/v1/sources/${source.id}`)) sent.push(Object.keys(r.postDataJSON() ?? {})); });
        await admin.locator('#set-collection').fill(`Disputes ${Date.now() % 1000}`);
        await admin.getByRole('button', { name: 'Save changes' }).click();
        const toast = await admin.locator('[data-sonner-toast]').first().innerText({ timeout: 15_000 }).catch(() => '');
        await admin.waitForTimeout(1000);
        await admin.screenshot({ path: join(SHOTS, 'source-settings-not-stored-1440.png') });
        // The knowledge base presets describe the search the service runs: keyword, with no rerank.
        await admin.goto(`${consoleUrl}/knowledge`, { waitUntil: 'load' });
        await admin.getByRole('button', { name: /New knowledge base/ }).first().click({ timeout: 60_000 });
        const presets = await admin.getByRole('dialog').innerText();
        const claims = /hybrid|rerank on/i.test(presets);
        await admin.context().close();
        const extra = sent.flat().filter((k) => !STORED.includes(k));
        check('13 an admin changes a source\'s schedule and is told it can\'t be saved yet; a save sends only what is stored', notice === 1 && scheduleOff && sent.length === 1 && !extra.length && /collection/i.test(toast) && !claims && /keyword/i.test(presets), { notice, scheduleOff, sent, extra, toast: toast.slice(0, 120), claims });
      });

      check('9 no page error', !errors.length, errors.slice(0, 5));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
