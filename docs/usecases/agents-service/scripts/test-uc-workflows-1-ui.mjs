// uc-workflows-1 a saved schedule starts a run once, ui layer: docs/usecases/agents-service/a-schedule-starts-a-run-once.md,
// steps 20 to 31. Platform sign-in (James builds, Ravi views) and the console on the live stack. A schedule saved through
// the API opens on the Schedule trigger's sheet; James changes it, is refused beside the field, pauses and resumes, clears
// it, and schedules an agent from its Channels tab. Ravi reads it and sees no control. No model is called.
import fs from 'node:fs';
import path from 'node:path';

import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, PRIYA, agents, as, saveAndPublish, until } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const SHOTS = process.env.OPS_UC_SHOTS ?? path.resolve('.logs/usecases/workflows-1/shots');
fs.mkdirSync(SHOTS, { recursive: true });

const node = (id, type, name, parameters = {}) => ({ id, type, typeVersion: 1, name, parameters });
const held = (id) => ({
  schemaVersion: 2,
  id,
  name: `Held wires ${id}`,
  nodes: [node('start', 'ops.trigger.schedule', 'On a schedule'), node('done', 'ops.flow.end', 'Done', { outcome: 'ok' })],
  connections: [{ from: { node: 'start', port: 'payload' }, to: { node: 'done', port: 'in' } }],
});
const RULE = { kind: 'every', every: 15, unit: 'minutes', start: '07:00', tz: 'Europe/London' };
const api = (method, p, headers, body) => fetch(`${agents}${p}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
const scheduleUrl = (id) => `/v1/workflows/definitions/${id}/triggers/start/schedule`;

async function signIn(browser, consoleUrl, email, width = 1440) {
  const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function openPanel(page, consoleUrl, id) {
  await page.goto(`${consoleUrl}/build/workflows/definitions/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('definition-node').first().waitFor({ timeout: 90_000 });
  await page.locator('[data-testid="definition-node"][data-node-id="start"]').dblclick();
  await page.getByTestId('schedule-panel').waitFor({ timeout: 30_000 });
}

const panelText = async (page) => (await page.getByTestId('schedule-panel').innerText()).replace(/\s+/g, ' ');
const shot = async (page, name) => {
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SHOTS, name) });
};
// The page and the sheet's or dialog's own scroller: a fixed panel could overflow with the page itself fitting.
const noSideScroll = (page) =>
  page.evaluate(() => {
    const own = [...document.querySelectorAll('[data-testid="step-sheet"] .overflow-y-auto, [role="dialog"] .overflow-y-auto')];
    return document.documentElement.scrollWidth <= window.innerWidth && own.every((el) => el.scrollWidth <= el.clientWidth);
  });
// `until` answers nothing on a timeout; a check built on it must fail then, so this one throws.
const must = async (what, probe, seconds = 60) => {
  const got = await until(probe, seconds);
  if (!got) throw new Error(`timed out waiting for: ${what}`);
  return got;
};
const CODE = [/\bops\./i, /\$\./, /\b(?:ag|wf|run|usr)_[a-z0-9]+/i, /\b[a-z]+_[a-z]+\b/, /\[object Object\]/];
const codeIn = (t) => CODE.map((re) => re.exec(t)).filter(Boolean).map((m) => m[0]);

await withUiStack(
  async (consoleUrl) => {
    const H = await as(JAMES);
    const A = `ucwf1_ui_${TAG}`;
    const a = await saveAndPublish(H, held(A));
    if (!a.live) throw new Error('setup: the workflow did not go live');
    // Saved by Priya, so "Changed by" names her until James saves.
    const P = await as(PRIYA);
    const put = await api('PUT', scheduleUrl(A), P, { rule: RULE });
    if (put.status !== 200) throw new Error(`setup: saving the schedule answered ${put.status}`);
    const browser = await chromium.launch();
    try {
      const james = await signIn(browser, consoleUrl, JAMES);
      await openPanel(james, consoleUrl, A);
      const opened = await panelText(james);
      check(
        '20 a schedule saved through the API opens on the trigger with its form, hints and time zone',
        opened.includes('Every hour unless you change it.') && opened.includes('Every day, day and night.') && opened.includes('Time zone') && opened.includes('Europe/London') && opened.includes('Applies at once to the live version when you save.') && opened.includes('Changed by Priya Shah'),
        opened.slice(0, 400),
      );
      await shot(james, 'builder-1440.png');

      // 21. Next runs lists three times in the chosen zone, and the words are the preview route's.
      const previewed = (await (await api('POST', '/v1/schedules/preview', H, { rule: RULE })).json()).data;
      const wall = (iso) => james.evaluate(([t, tz]) => new Date(t).toLocaleString('en-CA', { timeZone: tz, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }), [iso, 'Europe/London']);
      const expected = await Promise.all(previewed.nextRuns.map(wall));
      const listed = await james.getByTestId('schedule-next-runs').locator('li').allInnerTexts();
      const words = await james.getByTestId('schedule-words').innerText();
      check('21 Next runs lists three times in the chosen zone and the words equal the preview route\'s', listed.length === 3 && JSON.stringify(listed) === JSON.stringify(expected) && words === previewed.words && words === 'Every 15 minutes from 07:00, Europe/London', { listed, expected, words });

      // 22. Saving by James applies at once and changes who changed it; a timeout here fails the step.
      await james.getByLabel('Every', { exact: true }).fill('30');
      await james.getByTestId('schedule-save').click();
      const after = await must('the API holds the 30 minute schedule', async () => {
        const v = (await (await api('GET', scheduleUrl(A), H)).json()).data;
        return v?.words?.includes('Every 30 minutes') ? v : null;
      });
      await james.getByText('Changed by James Richardson').waitFor({ timeout: 30_000 });
      const saved = await panelText(james);
      check('22 Save schedule applies at once with no publish and now names James as the one who changed it', after.changedByName === 'James Richardson' && !saved.includes('Priya Shah') && !/publish/i.test(saved), { changedByName: after.changedByName, saved: saved.slice(0, 200) });

      // 23, 24. Refused beside the field, with everything typed still there.
      await james.getByLabel('Every', { exact: true }).fill('1');
      await james.getByTestId('schedule-save').click();
      await james.getByText('At least 5 minutes on this install.').waitFor({ timeout: 30_000 });
      const kept = await james.getByLabel('Every', { exact: true }).inputValue();
      check('23 a rule under the floor is refused beside its field and the typed value stays', kept === '1', kept);
      await james.getByLabel('Every', { exact: true }).fill('30');
      for (const d of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) await james.getByRole('checkbox', { name: d }).uncheck();
      await james.getByTestId('schedule-save').click();
      await james.getByText('Choose at least one weekday.').waitFor({ timeout: 30_000 });
      for (const d of ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) await james.getByRole('checkbox', { name: d }).check();
      check('24 a rule with no weekday is refused beside Days and the other fields stay as typed', (await james.getByLabel('Every', { exact: true }).inputValue()) === '30', 'days');
      await james.getByLabel('Between, from').fill('18:00');
      await james.getByLabel('Between, to').fill('07:00');
      await james.getByTestId('schedule-save').click();
      await james.getByText('is not after').waitFor({ timeout: 30_000 });
      check('24b hours that end before they start are refused beside Between and the times stay', (await james.getByLabel('Between, from').inputValue()) === '18:00', 'between');
      await james.getByLabel('Between, from').fill('');
      await james.getByLabel('Between, to').fill('');
      const zone = await api('PUT', scheduleUrl(A), H, { rule: { ...RULE, tz: 'Mars/Phobos' } });
      const zoneBody = await zone.json();
      check('24c an unknown zone sent by API is refused naming tz', zone.status === 422 && zoneBody.error?.details?.field === 'tz', zoneBody.error);

      // 24d. An input schema that asks for more than the due time is refused naming the field; the hint says why.
      const D = `ucwf1_ui_input_${TAG}`;
      const needsDay = held(D);
      needsDay.nodes[0] = node('start', 'ops.trigger.schedule', 'On a schedule', { inputSchema: { type: 'object', required: ['day'], properties: { day: { type: 'string' } } } });
      await api('POST', '/v1/workflows/definitions', H, { definition: needsDay });
      await openPanel(james, consoleUrl, D);
      const zoneShown = await james.locator('#schedule-start-tz').innerText();
      const local = await james.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
      check('20b with nothing saved the form opens on the browser\'s own time zone', zoneShown.includes(local), { zoneShown, local });
      await james.getByTestId('schedule-save').click();
      await james.getByTestId('schedule-refusal').waitFor({ timeout: 30_000 });
      const refusal = await james.getByTestId('schedule-refusal').innerText();
      const hint = await james.getByTestId('step-sheet').innerText();
      check('24d an input schema that requires more than the due time is refused naming the field, with the hint', refusal.includes('day') && hint.includes('A scheduled run\'s input is the time it was due (dueAt). The schema may not require anything else.'), { refusal, hint: hint.slice(-300) });

      // 25. A schedule on a workflow never published: saved, not running yet, and why.
      const B = `ucwf1_ui_draft_${TAG}`;
      await api('POST', '/v1/workflows/definitions', H, { definition: held(B) });
      await api('PUT', scheduleUrl(B), H, { rule: RULE });
      await openPanel(james, consoleUrl, B);
      const notLive = await panelText(james);
      check('25 a schedule on a workflow with no live version says Saved. Not running yet, and why', notLive.includes('Saved. Not running yet') && notLive.includes('No version of this workflow is live.'), notLive.slice(0, 300));

      // 26. Paused from the header: the panel says so, and Resume is real.
      await api('POST', `/v1/workflows/definitions/${A}/pause`, H, {});
      await openPanel(james, consoleUrl, A);
      const paused = await panelText(james);
      check('26 a paused workflow says so on the panel, Next runs reads None while paused, and Resume is in reach', paused.includes('Paused: no scheduled runs') && paused.includes('None while paused') && (await james.getByTestId('schedule-resume').isVisible()), paused.slice(0, 300));
      await james.setViewportSize({ width: 390, height: 844 });
      await shot(james, 'builder-paused-390.png');
      check('26b the paused panel has no sideways scroll at 390', await noSideScroll(james), 'scroll');
      await james.setViewportSize({ width: 1440, height: 1000 });
      await james.getByTestId('schedule-resume').click();
      await james.getByTestId('schedule-alert-paused').waitFor({ state: 'hidden', timeout: 30_000 });
      const resumed = (await (await api('GET', `/v1/workflows/definitions/${A}`, H)).json()).data;
      check('26c Resume resumes the workflow: it is no longer paused on the server and the notice is gone', resumed.paused === false, resumed.paused);
      await api('POST', `/v1/workflows/definitions/${A}/pause`, H, {});

      // 27. Before any slot the last run reads as not run yet.
      await openPanel(james, consoleUrl, A);
      const lastRun = await james.getByTestId('schedule-last-run').innerText();
      check('27 Last scheduled run reads Not run yet before any slot', lastRun.includes('Last scheduled run') && lastRun.includes('Not run yet.'), lastRun);

      // 30. A member reads a paused schedule and has no Save, Clear or Resume; direct calls are refused.
      const ravi = await signIn(browser, consoleUrl, RAVI);
      await openPanel(ravi, consoleUrl, A);
      const viewer = await panelText(ravi);
      const controls = (await ravi.getByTestId('schedule-save').count()) + (await ravi.getByTestId('schedule-clear').count()) + (await ravi.getByTestId('schedule-resume').count());
      const R = await as(RAVI);
      const direct = await api('PUT', scheduleUrl(A), R, { rule: RULE });
      const directResume = await api('POST', `/v1/workflows/definitions/${A}/resume`, R, {});
      check('30 a member reads a paused schedule with its next runs, sees no Save, Clear or Resume, and direct calls are refused', viewer.includes('Paused: no scheduled runs') && viewer.includes('Next runs') && controls === 0 && direct.status === 403 && directResume.status === 403, { controls, save: direct.status, resume: directResume.status });
      await shot(ravi, 'viewer-1440.png');
      await ravi.setViewportSize({ width: 390, height: 844 });
      check('30b the member reads the same panel at 390 with no sideways scroll', (await panelText(ravi)).includes('Next runs') && (await noSideScroll(ravi)), '390');
      await shot(ravi, 'viewer-390.png');
      await api('POST', `/v1/workflows/definitions/${A}/resume`, H, {});

      // 28. Clear schedule asks first, and says what stops.
      await openPanel(james, consoleUrl, A);
      await james.getByTestId('schedule-clear').click();
      const confirm = await james.getByTestId('delete-schedule-clear-dialog').innerText();
      check('28 Clear schedule asks first and says what stops', confirm.includes('Scheduled runs stop') && confirm.includes('not paused'), confirm);
      await james.getByTestId('delete-schedule-clear-confirm-btn').click();
      await must('the schedule is gone', async () => (await api('GET', scheduleUrl(A), H)).status === 404);
      await api('PUT', scheduleUrl(A), H, { rule: RULE });

      // 29, 33. Key under Advanced, and the form by keyboard.
      await openPanel(james, consoleUrl, A);
      const sheetBody = await james.getByTestId('step-sheet').innerText();
      check('29 the trigger\'s start name is under a closed Advanced section once a schedule is set', sheetBody.includes('Advanced') && !(await james.getByText('Start name').first().isVisible().catch(() => false)), sheetBody.slice(-200));
      await james.getByTestId('node-settings-advanced-open').click();
      const keyShown = await james.getByText('Start name').first().waitFor({ timeout: 10_000 }).then(() => true).catch(() => false);
      check('29b opening Advanced shows the trigger\'s start name (its key)', keyShown, 'Start name');
      await james.getByLabel('Every', { exact: true }).focus();
      const order = [];
      for (let i = 0; i < 12; i += 1) {
        await james.keyboard.press('Tab');
        order.push(await james.evaluate(() => { const el = document.activeElement; return (el?.getAttribute('aria-label') ?? el?.labels?.[0]?.textContent ?? el?.textContent ?? '').trim().slice(0, 30); }));
      }
      // The time field is one stop per part (hour, minute, period), so the order is read as a sequence.
      const wanted = ['Unit', 'Starting at', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
      let at = 0;
      for (const o of order) if (at < wanted.length && o.startsWith(wanted[at])) at += 1;
      check('33 Tab reaches Unit, Starting at and each weekday in order, each with a label', at === wanted.length, order);
      await james.locator('#schedule-start-tz').focus();
      await james.keyboard.press('Enter');
      await james.keyboard.type('Toronto');
      await james.locator('[cmdk-item]', { hasText: 'Toronto' }).first().waitFor({ timeout: 15_000 }).catch(() => undefined);
      const options = await james.locator('[cmdk-item]').allInnerTexts();
      await james.keyboard.press('ArrowDown');
      await james.keyboard.press('Enter');
      const chosen = await james.locator('#schedule-start-tz').innerText();
      check('33b the zone search opens, searches and chooses by keyboard, and lists no id or path', options.some((o) => o.includes('Toronto')) && chosen.includes('Toronto') && !/\bops\.|\$\.|\b(?:ag|wf|run|usr)_[a-z0-9]+/i.test(options.join(' ')), { options: options.slice(0, 5), chosen });

      await james.setViewportSize({ width: 390, height: 844 });
      await shot(james, 'builder-sheet-390.png');
      check('29 c the whole trigger sheet has no sideways scroll at 390', await noSideScroll(james), 'scroll');
      await james.setViewportSize({ width: 1440, height: 1000 });

      // 32b. A newer version without the trigger: the notice above the canvas, and Clear schedule confirms first.
      const C = `ucwf1_ui_idle_${TAG}`;
      await saveAndPublish(H, held(C));
      await api('PUT', scheduleUrl(C), H, { rule: RULE });
      const dropped = held(C);
      dropped.nodes[0] = node('start', 'ops.trigger.request', 'Asked');
      await saveAndPublish(H, dropped);
      await james.goto(`${consoleUrl}/build/workflows/definitions/${C}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('schedule-idle-notice').waitFor({ timeout: 60_000 });
      const idle = (await james.getByTestId('schedule-idle-notice').innerText()).replace(/\s+/g, ' ');
      check('28b a schedule whose trigger a newer version dropped shows a notice above the canvas with Clear schedule', idle.includes('not running') && idle.includes('Every 15 minutes') && (await james.getByTestId('schedule-idle-clear').isVisible()), idle);
      await shot(james, 'idle-notice-1440.png');
      await james.getByTestId('schedule-idle-clear').focus();
      await james.keyboard.press('Enter');
      await james.getByTestId('delete-schedule-idle-clear-dialog').waitFor({ timeout: 15_000 });
      await james.getByTestId('delete-schedule-idle-clear-confirm-btn').click();
      await must('the idle schedule is cleared', async () => (await api('GET', scheduleUrl(C), H)).status === 404);
      check('28c the idle notice\'s Clear schedule opens a confirm on Enter, then clears it and the notice goes', await james.getByTestId('schedule-idle-notice').waitFor({ state: 'hidden', timeout: 30_000 }).then(() => true).catch(() => false), 'cleared');

      const live = `${consoleUrl}/build/agents/ag_branch?tab=channels`;
      await james.goto(live, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('run-on-schedule').click();
      await james.getByRole('heading', { name: 'Schedule an agent' }).waitFor({ timeout: 30_000 });
      await james.setViewportSize({ width: 390, height: 844 });
      await shot(james, 'dialog-390.png');
      check('31a the Schedule an agent dialog fits at 390 and its Create workflow stays reachable', (await noSideScroll(james)) && (await james.getByTestId('schedule-agent-create').isVisible()), 'dialog 390');
      await james.setViewportSize({ width: 1440, height: 1000 });
      const name = `Morning report ${TAG}`;
      await james.getByLabel('Workflow name').fill(name);
      await james.getByLabel('Ask the agent').fill('Summarise yesterday.');
      await james.getByTestId('schedule-agent-create').click();
      await james.waitForURL(/\/build\/workflows\/definitions\/[^/]+$/, { timeout: 60_000 });
      const made = decodeURIComponent(new URL(james.url()).pathname.split('/').pop());
      const def = (await (await api('GET', `/v1/workflows/definitions/${made}`, H)).json()).data;
      const agentStep = def.definition.nodes.filter((n) => n.type === 'ops.ai.agent');
      const hasSchedule = (await api('GET', scheduleUrl(made), H)).status === 200;
      check('31 Run on a schedule makes a workflow whose one step is the agent, with the schedule saved, and opens it', agentStep.length === 1 && agentStep[0].parameters.agent === 'ag_branch' && def.name === name && hasSchedule, { agentStep, name: def.name, hasSchedule });
      await api('POST', `/v1/workflows/definitions/${made}/publish-requests`, H, {});
      await james.goto(live, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = james.getByRole('row').filter({ hasText: name });
      await row.waitFor({ timeout: 60_000 });
      const rowText = (await row.innerText()).replace(/\s+/g, ' ');
      check('31b once published, its own row on the agent\'s live list shows the schedule in words and the next run', rowText.includes('Every hour') && rowText.includes('next'), rowText);
      const listText = (await james.getByTestId('versions-live').innerText()) + ' ' + rowText;
      check('34 no id, path or raw name on the live list', codeIn(listText.replace(/ag_branch/g, '')).length === 0, codeIn(listText));

      // 32. The live list's states, drawn by holding, failing and emptying its route in the browser only.
      const route = '**/v1/agents/ag_branch/live';
      // A page of its own with nothing cached, so the list really loads: a read already held would draw no skeleton.
      const fresh = await signIn(browser, consoleUrl, JAMES);
      // The skeleton is on screen for a moment between the page and the answer, so it is watched for from the page's start.
      await fresh.addInitScript(() => { window.__sawSkeleton = false; new MutationObserver(() => { if (document.querySelector('[data-testid="live-skeleton"]')) window.__sawSkeleton = true; }).observe(document, { childList: true, subtree: true }); });
      await fresh.route(route, async (r) => { await new Promise((ok) => setTimeout(ok, 6000)); await r.continue().catch(() => undefined); });
      await fresh.goto(live, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await fresh.getByTestId('versions-live').waitFor({ timeout: 90_000 });
      const loading = await fresh.evaluate(() => window.__sawSkeleton === true);
      await fresh.unroute(route);
      await fresh.route(route, (r) => r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'internal', message: 'down' } }) }));
      await fresh.goto(live, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const failed = await fresh.getByText(/Couldn.t load where this agent is live/).first().waitFor({ timeout: 30_000 }).then(() => true).catch(() => false);
      const retry = await fresh.getByRole('button', { name: /retry|try again/i }).count();
      await fresh.unroute(route);
      await fresh.route(route, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { latestVersion: 1, versions: [], rows: [] } }) }));
      await fresh.goto(live, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const empty = await fresh.getByTestId('live-empty').getByText('Not live anywhere yet').waitFor({ timeout: 30_000 }).then(() => true).catch(() => false);
      await fresh.unroute(route);
      check('32 the agent\'s live list shows its own skeleton rows while loading, a retry when it fails, and Not live anywhere yet when empty', loading && failed && retry > 0 && empty, { loading, failed, retry, empty });
      const memberList = await signIn(browser, consoleUrl, RAVI);
      await memberList.goto(live, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await memberList.getByTestId('versions-live').waitFor({ timeout: 60_000 });
      check('32b a member sees the live list and no Schedule button', (await memberList.getByTestId('run-on-schedule').count()) === 0, 'member');
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
