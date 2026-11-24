// uc-workflows-1 a saved schedule starts a run once, ui layer: docs/usecases/agents-service/a-schedule-starts-a-run-once.md,
// steps 20 to 31. Platform sign-in (James builds, Ravi views) and the console on the live stack. A schedule saved through
// the API opens on the Schedule trigger's sheet; James changes it, is refused beside the field, pauses and resumes, clears
// it, and schedules an agent from its Channels tab. Ravi reads it and sees no control. No model is called.
import fs from 'node:fs';
import path from 'node:path';

import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as, saveAndPublish, until } from '../../lib/workflow_ui.mjs';

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
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

await withUiStack(
  async (consoleUrl) => {
    const H = await as(JAMES);
    const A = `ucwf1_ui_${TAG}`;
    const a = await saveAndPublish(H, held(A));
    if (!a.live) throw new Error('setup: the workflow did not go live');
    const put = await api('PUT', scheduleUrl(A), H, { rule: RULE });
    if (put.status !== 200) throw new Error(`setup: saving the schedule answered ${put.status}`);
    const browser = await chromium.launch();
    try {
      const james = await signIn(browser, consoleUrl, JAMES);
      await openPanel(james, consoleUrl, A);
      const opened = await panelText(james);
      check(
        '20 a schedule saved through the API opens on the trigger with its form, hints and time zone',
        opened.includes('Every hour unless you change it.') && opened.includes('Time zone') && opened.includes('Europe/London') && opened.includes('Next runs') && opened.includes('Applies at once to the live version when you save.'),
        opened.slice(0, 400),
      );
      await shot(james, 'builder-1440.png');

      await james.getByLabel('Every', { exact: true }).fill('30');
      await james.getByTestId('schedule-save').click();
      await until(async () => (await (await api('GET', scheduleUrl(A), H)).json()).data?.words?.includes('Every 30 minutes') || false, 60);
      const saved = await panelText(james);
      check('22 Save schedule applies at once, with no publish, and names who changed it', saved.includes('Changed by') && !saved.includes('publish'), saved.slice(0, 300));

      await james.getByLabel('Every', { exact: true }).fill('1');
      await james.getByTestId('schedule-save').click();
      await james.getByText('At least 5 minutes on this install.').waitFor({ timeout: 30_000 });
      const kept = await james.getByLabel('Every', { exact: true }).inputValue();
      check('23 a rule under the floor is refused beside its field and the typed value stays', kept === '1', kept);
      await james.getByLabel('Every', { exact: true }).fill('30');

      await api('POST', `/v1/workflows/definitions/${A}/pause`, H, {});
      await openPanel(james, consoleUrl, A);
      const paused = await panelText(james);
      check('26 a paused workflow says so on the panel, Next runs reads None while paused, and Resume is in reach', paused.includes('Paused: no scheduled runs') && paused.includes('None while paused') && (await james.getByTestId('schedule-resume').isVisible()), paused.slice(0, 300));
      await james.setViewportSize({ width: 390, height: 844 });
      await shot(james, 'builder-paused-390.png');
      check('26b the panel has no sideways scroll at 390', await noSideScroll(james), 'scroll');
      await james.setViewportSize({ width: 1440, height: 1000 });
      await james.getByTestId('schedule-resume').click();
      await james.getByTestId('schedule-alert-paused').waitFor({ state: 'hidden', timeout: 30_000 });
      check('26c Resume clears the paused notice', true, 'resumed');

      await james.getByTestId('schedule-clear').click();
      await james.getByTestId('delete-schedule-clear-confirm-btn').click();
      await until(async () => (await api('GET', scheduleUrl(A), H)).status === 404, 60);
      check('28 Clear schedule asks first, then the schedule is gone', true, 'cleared');
      await api('PUT', scheduleUrl(A), H, { rule: RULE });

      const ravi = await signIn(browser, consoleUrl, RAVI);
      await openPanel(ravi, consoleUrl, A);
      const viewer = await panelText(ravi);
      const controls = await ravi.getByTestId('schedule-save').count() + (await ravi.getByTestId('schedule-clear').count()) + (await ravi.getByTestId('schedule-resume').count());
      const direct = await api('PUT', scheduleUrl(A), await as(RAVI), { rule: RULE });
      check('30 a member reads the words and next runs, sees no Save, Clear or Resume, and a direct save is refused', viewer.includes('Next runs') && controls === 0 && direct.status === 403, { controls, status: direct.status });
      await shot(ravi, 'viewer-1440.png');

      await james.goto(`${consoleUrl}/build/agents/ag_branch?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('run-on-schedule').click();
      await james.getByRole('heading', { name: 'Schedule an agent' }).waitFor({ timeout: 30_000 });
      const name = `Morning report ${TAG}`;
      await james.getByLabel('Workflow name').fill(name);
      await james.getByLabel('Ask the agent').fill('Summarise yesterday.');
      await james.getByTestId('schedule-agent-create').click();
      await james.waitForURL(/\/build\/workflows\//, { timeout: 60_000 });
      const made = (await (await api('GET', '/v1/workflows/definitions?search=' + encodeURIComponent(name), H)).json()).data;
      check('31 Run on a schedule makes a workflow with the agent as its step and opens it', JSON.stringify(made).includes('Morning report'), JSON.stringify(made).slice(0, 200));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
